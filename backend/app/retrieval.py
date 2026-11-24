"""Versioned chunks, semantic indexing, and rank fusion for policy evidence."""
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from unicodedata import normalize

from .schema import EvidenceMatch, Policy


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", normalize("NFKC", text).lower())
    return [word for word in words if word not in {
        "a", "an", "and", "can", "do", "for", "from", "have", "how", "i", "is",
        "it", "of", "the", "to", "what", "when", "where"
    }]


@dataclass(frozen=True)
class Chunk:
    id: str
    policy: Policy
    text: str


def policy_chunks(policies: list[Policy]) -> list[Chunk]:
    chunks = []
    for policy in policies:
        for i, paragraph in enumerate(policy.text.split("\n\n"), 1):
            if paragraph.strip():
                chunks.append(Chunk(f"{policy.id}#{i}", policy, paragraph.strip()))
    return chunks


class Embedder(Protocol):
    def __call__(self, texts: list[str]) -> list[list[float]]: ...


class PolicyRetriever:
    def __init__(
        self, policies: list[Policy], *, path: Path | None = None,
        embed: Embedder | None = None, embedding_id: str = "",
    ):
        self.chunks = {chunk.id: chunk for chunk in policy_chunks(policies)}
        self.term_counts = {
            cid: Counter(tokens(chunk.policy.title + " " + chunk.text))
            for cid, chunk in self.chunks.items()
        }
        self.embed = embed
        self.collection = None
        if embed is None:
            return
        if path is None or not embedding_id:
            raise ValueError("Semantic retrieval requires an index path and embedding identifier")

        import chromadb

        # Hash both corpus and encoder identity. A rebuild cannot mix versions
        # or vectors from different models under the same collection.
        rows = [(cid, chunk.policy.version, chunk.policy.title, chunk.text)
                for cid, chunk in self.chunks.items()]
        fingerprint = hashlib.sha256(json.dumps([embedding_id, rows]).encode()).hexdigest()[:24]
        client = chromadb.PersistentClient(path=str(path))
        self.collection = client.get_or_create_collection(
            f"policies-{fingerprint}", embedding_function=None, configuration={"hnsw": {"space": "cosine"}},
        )
        if self.collection.count() != len(rows):
            self.collection.upsert(
                ids=[row[0] for row in rows],
                documents=[row[3] for row in rows],
                metadatas=[{"policy_id": self.chunks[row[0]].policy.id, "version": row[1]} for row in rows],
                embeddings=embed([f"{row[2]}\n{row[3]}" for row in rows]),
            )

    @property
    def mode(self) -> Literal["keyword", "hybrid"]:
        return "hybrid" if self.collection is not None else "keyword"

    def search(self, query: str, limit: int = 3) -> list[EvidenceMatch]:
        if limit < 1 or not query.strip() or not self.chunks:
            return []
        lexical = self._keyword(query)
        semantic = []
        if self.collection is not None and self.embed is not None:
            hits = self.collection.query(
                query_embeddings=self.embed([query]),
                n_results=min(6, len(self.chunks)),
                include=["distances"],
            )
            # Reject weak semantic-only matches before combining ranks. The
            # cutoff is a demo heuristic, evaluated separately from citations.
            semantic = [
                cid for cid, distance in zip(hits["ids"][0], hits["distances"][0], strict=True)
                if distance <= 0.80
            ]

        # Reciprocal rank fusion avoids comparing BM25 against cosine scores.
        ranks = Counter()
        for ranking in (lexical, semantic):
            for position, cid in enumerate(ranking, 1):
                ranks[cid] += 1 / (10 + position)
        return [
            EvidenceMatch(chunk_id=cid, policy_id=self.chunks[cid].policy.id,
                          excerpt=self.chunks[cid].text,
                          keyword=cid in lexical, semantic=cid in semantic)
            for cid in sorted(ranks, key=lambda item: (-ranks[item], item))[:limit]
        ]

    def _keyword(self, query: str) -> list[str]:
        scores = Counter()
        counts = self.term_counts
        average = sum(sum(terms.values()) for terms in counts.values()) / len(counts)
        if not average:
            return []
        for term in sorted(set(tokens(query))):
            frequency = sum(term in terms for terms in counts.values())
            weight = math.log1p((len(counts) - frequency + 0.5) / (frequency + 0.5))
            for cid, terms in counts.items():
                if (tf := terms[term]):
                    norm = 1.2 * (0.25 + 0.75 * sum(terms.values()) / average)
                    scores[cid] += weight * (tf * 2.2) / (tf + norm)
        return sorted(scores, key=lambda cid: (-scores[cid], cid))[:6]


def model_identity(directory: Path) -> str:
    """Bind cached vectors to the local weights and tokenizer configuration."""
    identity = hashlib.sha256()
    weights = sorted(directory.glob("*.safetensors"))
    if not weights:
        raise ValueError("Expected safetensors weights in the local model directory")
    files = sorted(
        path for path in directory.rglob("*")
        if path.suffix in {".safetensors", ".json", ".txt"}
        and not any(part.startswith(".") for part in path.relative_to(directory).parts)
        and path.is_file()
    )
    for path in files:
        with path.open("rb") as stream:
            identity.update(path.relative_to(directory).as_posix().encode())
            identity.update(hashlib.file_digest(stream, "sha256").digest())
    return identity.hexdigest()


def sentence_encoder(model: str) -> Embedder:
    from sentence_transformers import SentenceTransformer

    encoder = SentenceTransformer(model, device="cpu", local_files_only=True, trust_remote_code=False)

    def embed(texts: list[str]) -> list[list[float]]:
        return encoder.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()

    return embed

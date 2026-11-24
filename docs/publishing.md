# Publish Error Dodge to GitHub

1. Review the staged files with `git status --short` and `git diff --cached --stat`. Use your GitHub no-reply commit email if you want to conceal your personal email.
2. On GitHub, create an empty repository named **Error-Dodge**. Start private if you would like to inspect it on GitHub before changing visibility. Leave the README, license, and .gitignore initialization options unchecked.
3. From the local repository, commit and push using your own Git identity. If you started from the source ZIP, first run `git init -b main` and `git add .`.

~~~powershell
git config user.name "YOUR_NAME"
git config user.email "YOUR_GITHUB_NOREPLY_EMAIL"
git commit -m "Add Error Dodge internship portfolio project"
git remote add origin https://github.com/YOUR_USERNAME/Error-Dodge.git
git push -u origin main
~~~

4. On GitHub, verify that the README images, Mermaid architecture, and relative documentation links render. Confirm the file tree has no real `.env`, `.secrets`, database, model weights, or local logs. Enable the repository's available secret scanning and push protection before making it public.
5. Add the description **Multi-agent AI reliability and evaluation platform with evidence-backed investigations and human review**. Suggested topics include `langgraph`, `fastapi`, `agentic-ai`, `rag`, `postgresql`, and `llm-evaluation`.

The repository is a locally verified portfolio release. Docker execution, public hosting, and live Gemini remain unverified. Choose a license before offering reuse rights. [GitHub publishing instructions](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)

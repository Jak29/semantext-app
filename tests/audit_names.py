"""The audit's name lists, as the audit's probes wrote them (probe_kinds.py, and the rows W2, W4, X1, X3, X4 and X11 of
the audit results for 91625c1 and 8f3c935). They are data for the evidence tests:
a structural policy must refuse every one of them outside its structure without looking at a name, and admit the
honest ones inside it. A name with "/" lies in a subfolder."""

# probe_kinds.py: honest names (W2 counted 24 of these refused at 91625c1)
HONEST_KINDS = ["LICENSE", "Makefile", "Dockerfile", ".gitignore", "index.html", "style.css", "run.sh", "run.ps1",
                "run.bat", "pom.xml", "setup.cfg", "pytest.ini", "README.rst", "nb.ipynb", "paper.tex", "main.go",
                "App.java", "lib.c", "lib.h", "x.cpp", "notes.MD", "CLAUDE.md", "a.py", "a.json", "a.yaml", "a.toml",
                "a.ts", "a.lean", "a.svg", "a.csv", "a.tsv", "a.log", "a.pdf", "a.png", "package-lock.json",
                "tokenizer.py", "secretary.md", "monkey.md", "tokens.md", "vault_notes.md"]
# X11 (8f3c935): innocent names, 16 of the first 16 refused by the name belt
HONEST_X11 = ["key.md", "seed.md", "cred.md", "keys.md", "key.py", "keys.py", "password_policy.md",
              "passwords_policy.md", "credentials_policy.md", "vaulted.md", "walleted.md", "wallets.md",
              "vault_notes.md", "tokens.md", "api_keys_doc.md", "kaggle_notes.md", "tokenizer.py", "secretary.md",
              "monkey.md", "keyboard.md", "keymap.json", "auth.md", "env.md", "token_budget.md", "key_results.md"]
HONEST = sorted(set(HONEST_KINDS + HONEST_X11))

# probe_kinds.py: secret-bearing names (W4: 37 of these digested at 91625c1)
SECRET_KINDS = ["wallet.json", "wallet.txt", "wallet.md", "vault.json", "vault.yaml", "vault.txt", "token.json",
                "tokens.json", "my_token.txt", "secret.json", "secrets.json", "secrets.yaml", "client_secret.json",
                "kaggle.json", "gh/hosts.yml", ".config/gh/hosts.yml", ".ssh_old/config.txt", ".ssh.bak/id.txt",
                ".sshd/x.txt", "service-account.json", "api_key.txt", "apikey.json", "password.txt", "passwords.csv",
                "seed.txt", "mnemonic.txt", "recovery_codes.txt", "access_token.txt", "auth.json", ".env.json",
                "env.json", "settings.local.json", ".claude/settings.local.json", "keys.json", "key.json",
                "private_key.json", "id_rsa.txt", "id_rsa", "x.key.md", ".kaggle/kaggle.json", ".aws/credentials.txt",
                "credentials.json", "cred.json"]
# X1 (8f3c935): the same words run together; 14 of 18 digested at 8f3c935
SECRET_X1 = ["mytoken.json", "apitoken.txt", "accesstoken.md", "clientsecret.json", "secretkey.txt", "secret_key.txt",
             "secret_key.json", "secret_value.txt", "secrets_prod.json", "token_file.json", "token_cache.json",
             "token-store.json", "tokens_cache.json", "TokenStore.json", "github_token.json", "bot-token.txt",
             "refresh_token.json", "auth_token.txt"]
# X3 (8f3c935): names not tried before; 34 of 35 digested at 8f3c935 (these are the ones the result names)
SECRET_X3 = ["oauth.json", "session.json", "cookies.json", "jwt.txt", "bearer.txt", "db_password.txt", "pass.txt",
             "passphrase.txt", "seed_phrase.md", "application_default_credentials.json", "gcp_credentials.json",
             "aws_credentials.txt", "appsettings.json", "settings.xml", "pip.ini", "rclone.ini", "env.sh",
             "secrets.sh"]
# X4 (8f3c935): logs and extensionless files that hold secrets
SECRET_X4 = ["app.log", "server.log", "access.log", "shadow", "passwd", "htpasswd", "authorized_keys", "known_hosts",
             "credentials", "kubeconfig"]
SECRET = sorted(set(SECRET_KINDS + SECRET_X1 + SECRET_X3 + SECRET_X4))

EVERY = sorted(set(HONEST + SECRET))


def plain(name: str) -> bool:
    """One segment with no leading dot: a name a document folder lists."""
    return "/" not in name and not name.startswith(".")

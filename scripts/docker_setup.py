"""Create isolated demo secrets once. Never overwrite an existing environment."""
from pathlib import Path
import os
import secrets

root = Path(__file__).resolve().parents[1]
path = root / '.env'
if path.exists():
    print('.env already exists; left unchanged. See docs/runbooks/docker.md for required keys.')
else:
    keys = ('POSTGRES_PASSWORD', 'READER_PASSWORD', 'MCP_INTERNAL_TOKEN',
            'VOICE_INTERNAL_TOKEN', 'API_SESSION_SECRET', 'CURSOR_SECRET')
    content = '# Synthetic local Docker demo only. Do not commit.\n'
    content += ''.join(f'{key}={secrets.token_hex(32)}\n' for key in keys)
    content += 'SEED_ROWS=1000000\nWEB_PORT=8080\n'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    print('Created .env with random local-only demo secrets (values not printed).')

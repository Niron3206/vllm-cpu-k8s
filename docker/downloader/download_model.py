"""скачивает веса модели с Hugging Face на том, если их там ещё нет
"""

import os
from pathlib import Path

PATTERNS = ["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja"]


def main():
    model_id = os.environ["MODEL_ID"]
    revision = os.environ["MODEL_REVISION"]
    model_dir = Path(os.environ["MODEL_DIR"])
    expected = f"{model_id}@{revision}"

    marker = model_dir / ".complete"
    if marker.is_file() and marker.read_text().strip() == expected:
        print(f"{expected} is already in {model_dir}, skipping download")
        return

    # когда модель уже на томе, библиотека не нужна
    from huggingface_hub import snapshot_download

    print(f"downloading {expected} to {model_dir}")
    snapshot_download(
        repo_id=model_id,
        revision=revision,
        local_dir=model_dir,
        allow_patterns=PATTERNS,
        # False, а не None: без токена не подхватывать чужой из окружения или кеша
        token=os.environ.get("HF_TOKEN") or False,
    )
    tmp = model_dir / ".complete.tmp"
    tmp.write_text(expected + "\n")
    tmp.replace(marker)
    print("done")


if __name__ == "__main__":
    main()

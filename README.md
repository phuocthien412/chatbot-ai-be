python -m venv .venv

.\.venv\Scripts\Activate

pip install -r requirements.txt

uvicorn src.main:app --reload
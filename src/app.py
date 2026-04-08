try:
    # exécution package: python -m src.app
    from .RemoteBorneManager import start_app
except ImportError:
    # exécution script: python src/app.py
    from RemoteBorneManager import start_app

if __name__ == "__main__":
    start_app()

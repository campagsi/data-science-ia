from src.cli import Console_APP

try:
    console = Console_APP()

    console.run()
except Exception as erro:
    print(f"{type(erro).__name__}: {erro}")

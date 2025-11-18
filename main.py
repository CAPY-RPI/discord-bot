"""Main entrypoint for the application."""

from config import settings


def main() -> None:
    """Main function to run the application."""
    settings.__sizeof__()


if __name__ == "__main__":
    main()

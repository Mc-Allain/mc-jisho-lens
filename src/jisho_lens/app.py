"""Application entry point.

Phase 0: only prints the detected display setup. The tray app arrives in Phase 1.
"""

from jisho_lens.core.displays import describe_displays, enable_per_monitor_dpi_awareness


def main() -> None:
    enable_per_monitor_dpi_awareness()
    print(describe_displays())


if __name__ == "__main__":
    main()

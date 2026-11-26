"""Launcher for the ITGmania Librarian.

Run from the repository root: python launch.py
"""

if __name__ == "__main__":
    # Imported here, not at module top, so a spawn child re-importing
    # this file as __mp_main__ does not pull in the UI module (and its
    # guarded Tkinter import) — the child only needs the data modules
    # (ChatGPT-6 follow-up 1, Revision 1).
    from itgmania_library.library_librarian import main

    main()

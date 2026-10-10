"""
Entry point:  python -m neograce [options] [files...]    (or: python run.py ...)

Command line options, like xmgrace:
  file.dat                   read x y columns as one set into G0
  file.agr / file.ngr        open a project
  -nxy file                  read x y1 y2 ... as several sets
  -settype xydy              data files after this are x y dy
  -block file -bxy 1:3[:4]   pick columns from a file
  -autoscale none            don't autoscale after reading
"""
import sys

from PySide6.QtWidgets import QApplication

from .io_formats import parse_columns
from .mainwindow import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("NeoGrace")
    window = MainWindow()
    window.resize(1150, 820)

    args = sys.argv[1:]
    set_type = "xy"
    autoscale = True
    block_file = None
    i = 0
    try:
        while i < len(args):
            arg = args[i]
            if arg == "-settype":
                set_type = args[i + 1].lower()
                i += 2
            elif arg == "-autoscale":
                autoscale = args[i + 1].lower() != "none"
                i += 2
            elif arg == "-nxy":
                window.load_data(args[i + 1], "nxy", set_type, None, None, autoscale)
                i += 2
            elif arg == "-block":
                block_file = args[i + 1]
                i += 2
            elif arg == "-bxy":
                window.load_data(block_file, "block", set_type, [parse_columns(args[i + 1])], None, autoscale)
                i += 2
            elif arg.lower().endswith(".agr") or arg.lower().endswith(".ngr"):
                window.open_path(arg)
                i += 1
            else:
                window.load_data(arg, "single", set_type, None, None, autoscale)
                i += 1
    except (IndexError, OSError, ValueError) as error:
        print("neograce: %s" % error, file=sys.stderr)

    window.project.modified = False
    window.update_title()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

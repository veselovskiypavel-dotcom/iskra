_PATH = r"C:\Users\Alina\Documents\Electronic Arts\The Sims 4\iskra_debug.log"


def log(msg):
    try:
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

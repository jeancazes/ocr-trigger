"""Conditions de texte : ET / OU / SAUF (PAS), parenthèses, « phrases entre guillemets », tolérance OCR.
Priorité : PAS > ET > OU.   « a SAUF b » = « a ET PAS b »."""
import difflib
import re
import unicodedata

AND, OR, NOT, EXC = {"et", "and"}, {"ou", "or"}, {"pas", "not"}, {"sauf", "except"}


def norm(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def tokenize(expr):
    toks = []
    for m in re.finditer(r'"([^"]*)"|(\()|(\))|([^\s()"]+)', str(expr)):
        if m.group(1) is not None:
            toks.append(("T", m.group(1)))
        elif m.group(2):
            toks.append(("(", "("))
        elif m.group(3):
            toks.append((")", ")"))
        else:
            w, lw = m.group(4), norm(m.group(4))
            kind = "AND" if lw in AND else "OR" if lw in OR else "NOT" if lw in NOT else "EXC" if lw in EXC else "W"
            toks.append((kind, w))
    return toks


class Parser:
    def __init__(self, expr):
        self.toks, self.i = tokenize(expr), 0

    def peek(self):
        return self.toks[self.i][0] if self.i < len(self.toks) else None

    def take(self):
        self.i += 1
        return self.toks[self.i - 1]

    def parse(self):
        if not self.toks:
            raise ValueError("vide")
        node = self.p_or()
        if self.i < len(self.toks):
            raise ValueError("« %s » inattendu" % self.toks[self.i][1])
        return node

    def p_or(self):
        node = self.p_and()
        while self.peek() == "OR":
            self.take()
            node = ("or", node, self.p_and())
        return node

    def p_and(self):
        node = self.p_not()
        while self.peek() in ("AND", "EXC"):
            k = self.take()[0]
            rhs = self.p_not()
            node = ("and", node, ("not", rhs) if k == "EXC" else rhs)
        return node

    def p_not(self):
        if self.peek() in ("NOT", "EXC"):
            self.take()
            return ("not", self.p_not())
        return self.p_atom()

    def p_atom(self):
        k = self.peek()
        if k == "(":
            self.take()
            node = self.p_or()
            if self.peek() != ")":
                raise ValueError("parenthèse « ) » manquante")
            self.take()
            return node
        if k in ("W", "T"):
            words = []
            while self.peek() == "W" or (not words and self.peek() == "T"):
                words.append(self.take()[1])
                if self.toks[self.i - 1][0] == "T":
                    break
            return ("term", " ".join(words))
        raise ValueError("terme attendu" if k is None else "« %s » inattendu" % self.toks[self.i][1])


def parse(expr):
    return Parser(expr).parse()


def validate(expr):
    """Lève ValueError (message lisible) si la condition est mal écrite."""
    parse(expr)


def contains(term, text, ratio=1.0):
    nt, nx = norm(term).strip(), norm(text)
    if not nt:
        return False
    if nt in nx:
        return True
    if ratio >= 1.0 or len(nt) < 4:
        return False
    n = len(nt)
    for L in {n - 1, n, n + 1}:
        for s in range(0, max(1, len(nx) - L + 1)):
            if difflib.SequenceMatcher(None, nt, nx[s:s + L]).ratio() >= ratio:
                return True
    return False


def evaluate(expr, text, ratio=1.0):
    """(résultat, [(terme, trouvé)]) — résultat False si la condition est invalide."""
    try:
        tree = parse(expr)
    except ValueError:
        return False, []
    seen = []

    def ev(n):
        if n[0] == "term":
            ok = contains(n[1], text, ratio)
            seen.append((n[1], ok))
            return ok
        if n[0] == "not":
            return not ev(n[1])
        a = ev(n[1])
        b = ev(n[2])  # pas de court-circuit : on veut le détail de chaque terme
        return (a and b) if n[0] == "and" else (a or b)
    return ev(tree), seen


def migrate(expr):
    """Anciennes règles « a|b » -> « a OU b »."""
    return re.sub(r"\s*\|\s*", " OU ", str(expr)) if "|" in str(expr) else expr

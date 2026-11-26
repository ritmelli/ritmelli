import codecs
import hashlib
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_DIGESTS = frozenset({
    "09e69063df51163253b956fb0bc3c4b99419457f5f41687cf7253d082507fb36",
    "387488942b84c8e512a97758ee016307a3b2bd4393252b6c4cad2655eb825c04",
    "4677a83dec38ea18a1802414f03db57589c75d8d7df9aa0cdbd6485d11310f97",
    "487b91042c7cf27a19e23ea8699f5f354b1a0c3af9e418138dc6150d830f970d",
    "53ffbd889105cbcd19843a9265510f9828c58f38add048270d58d742f7ff64db",
    "7d3194f79e645c42e4396dda38be04766810ec6a00d00aced3ffc2a0a1f1a9ef",
    "c388b308f3c72f5c916682777f6d4c81f2895bb1dbce9de77b7f9604e1e71ca3",
    "cb8749ec66d05b91819157a626b12a57328b20f72179966419c65ccf946c59de",
    "e853b4e183ed08708fa41b2f88448464fcfd3b5e1b60d5ab5be260189df707b0",
})
TOKEN = re.compile(r"[^\W_]+")
PAIR_SEPARATORS = frozenset({"-", " ", "_"})
DOTTED_AND_DOTLESS_I = str.maketrans({chr(0x130): "I", chr(0x131): "i"})
UNICODE_BOMS = ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"), (codecs.BOM_UTF16_LE, "utf-16"),
                (codecs.BOM_UTF16_BE, "utf-16"))
UTF16_ASCII_RUNS = {"utf-16-le": re.compile(rb"(?:[\t\n\r\x20-\x7e]\x00)+"),
                    "utf-16-be": re.compile(rb"(?:\x00[\t\n\r\x20-\x7e])+")}
PRINTABLE_RUN = re.compile(rb"[\t\x20-\x7e]{4,}")
MODEL_WEIGHT_SUFFIXES = frozenset({".onnx"})
BINARY_SIGNATURES = {suffix: re.compile(signature, re.DOTALL) for suffix, signature in (
    (".png", rb"\x89PNG\r\n\x1a\n"), (".ico", rb"\x00\x00\x01\x00"), (".exe", rb"MZ"), (".onnx", rb"\x08[\x01-\x7f]\x12"),
    (".woff2", rb"wOF2"), (".webp", rb"RIFF....WEBP"))}


def digest(term):
    return hashlib.sha256(term.encode("utf-8")).hexdigest()


def candidate_terms(line):
    line = line.translate(DOTTED_AND_DOTLESS_I).casefold()
    tokens = list(TOKEN.finditer(line))
    for i, token in enumerate(tokens):
        yield token.group()
        if i + 1 < len(tokens):
            following = tokens[i + 1]
            if line[token.end():following.start()] in PAIR_SEPARATORS:
                yield f"{token.group()} {following.group()}"


def find_hits(text, digests):
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        for term in candidate_terms(line):
            h = digest(term)
            if h in digests:
                hits.append((number, h))
    return hits


def has_binary_signature(name, data):
    signature = BINARY_SIGNATURES.get(Path(name).suffix.lower())
    return signature is not None and signature.match(data) is not None


def readings(name, data):
    for bom, encoding in UNICODE_BOMS:
        if data.startswith(bom):
            return [data.decode(encoding, errors="replace")]
    if has_binary_signature(name, data):
        texts = ["\n".join(run.group().decode(encoding) for run in pattern.finditer(data))
                 for encoding, pattern in UTF16_ASCII_RUNS.items()]
        if Path(name).suffix.lower() not in MODEL_WEIGHT_SUFFIXES:
            texts.append("\n".join(run.group().decode("ascii") for run in PRINTABLE_RUN.finditer(data)))
        return texts
    if b"\0" not in data:
        return [data.decode("utf-8", errors="replace")]
    return [data.decode(encoding, errors="replace") for encoding in (*UTF16_ASCII_RUNS, "utf-8")]


def tracked_files():
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    files, missing = {}, []
    for name in filter(None, listed.decode("utf-8").split("\0")):
        path = ROOT / name
        if path.is_file():
            files[name] = path.read_bytes()
        else:
            missing.append(name)
    return files, missing


def scan(files, digests):
    return sorted({(name, number, h) for name, data in files.items() for text in readings(name, data)
                   for number, h in find_hits(text, digests)})


class TrackedFiles(unittest.TestCase):
    def test_no_tracked_file_has_a_forbidden_term(self):
        files, missing = tracked_files()
        self.assertEqual(missing, [], "tracked files missing from the working tree are not scanned")
        self.assertGreater(len(files), 100)
        hits = scan(files, FORBIDDEN_DIGESTS)
        signed = sum(has_binary_signature(name, data) for name, data in files.items())
        print(f"scanned {len(files)} tracked files ({signed} signed binaries read only by their runs), {len(hits)} hits",
              file=sys.stderr)
        self.assertEqual([f"{name}:{number} (term digest {h[:12]})" for name, number, h in hits], [])

    def test_every_binary_signature_is_in_use(self):
        files, _ = tracked_files()
        signed = {Path(name).suffix.lower() for name, data in files.items() if has_binary_signature(name, data)}
        self.assertEqual(signed, set(BINARY_SIGNATURES))

    def test_the_digests_are_sha256_hex(self):
        self.assertEqual(len(FORBIDDEN_DIGESTS), 9)
        for h in FORBIDDEN_DIGESTS:
            self.assertRegex(h, r"^[0-9a-f]{64}$")

    def test_harmless_words_that_contain_a_term_pass(self):
        sample = "re.fullmatch(pattern, text)\nmatches = [m for m in fullmatches if m]\n"
        self.assertEqual(find_hits(sample, FORBIDDEN_DIGESTS), [])


class Matcher(unittest.TestCase):
    SINGLE = frozenset({digest("kiwi")})
    PAIR = frozenset({digest("kiwi fruit")})
    PNG = b"\x89PNG\r\n\x1a\n\x00\x00"

    def hits(self, name, data):
        return scan({name: data}, self.SINGLE)

    def test_a_single_term_matches_as_a_whole_token_in_any_case(self):
        for line in ("kiwi", "Kiwi!", "a KIWI here", "x = kiwi_box", "(kiwi)", "kiwi-box", "K" + chr(0x130) + "W" + chr(0x130),
                     "k" + chr(0x131) + "w" + chr(0x131)):
            self.assertEqual(len(find_hits(line, self.SINGLE)), 1, line)

    def test_a_single_term_inside_a_longer_word_passes(self):
        for line in ("kiwis", "akiwi", "kiwi2", "kiwifruit", "kíwi"):
            self.assertEqual(find_hits(line, self.SINGLE), [], line)

    def test_a_pair_matches_with_one_hyphen_space_or_underscore(self):
        for line in ("kiwi-fruit", "Kiwi Fruit", "KIWI_FRUIT", "a kiwi-fruit b", "ß kiwi fruit", "ẞ ß Kiwi-Fruit"):
            self.assertEqual(len(find_hits(line, self.PAIR)), 1, line)

    def test_a_pair_split_any_other_way_passes(self):
        for line in ("kiwi  fruit", "kiwi.fruit", "kiwi--fruit", "kiwi", "fruit kiwi", "kiwis fruit"):
            self.assertEqual(find_hits(line, self.PAIR), [], line)
        self.assertEqual(find_hits("kiwi\nfruit", self.PAIR), [])

    def test_the_hit_carries_its_line_number(self):
        self.assertEqual(find_hits("one\ntwo kiwi\nthree\nkiwi", self.SINGLE),
                         [(2, digest("kiwi")), (4, digest("kiwi"))])

    def test_unicode_text_with_a_byte_order_mark_is_read(self):
        for encoding in ("utf-16", "utf-32"):
            for byteorder in ("le", "be"):
                data = (chr(0xFEFF) + "one\r\nkiwi\r\n").encode(f"{encoding}-{byteorder}")
                self.assertEqual(self.hits("notes.txt", data), [("notes.txt", 2, digest("kiwi"))], (encoding, byteorder))

    def test_utf16_text_without_a_byte_order_mark_is_read_under_any_name(self):
        for encoding in UTF16_ASCII_RUNS:
            data = (chr(0x108) + "one\r\nkiwi\r\n").encode(encoding)
            for name in ("docs/note.png", "modelos/note.onnx", "instalador/tool.ps1", "notes"):
                self.assertEqual(self.hits(name, data), [(name, 2, digest("kiwi"))], (encoding, name))

    def test_utf16_text_with_no_nul_until_late_is_read(self):
        for encoding in UTF16_ASCII_RUNS:
            data = (chr(0x4E2D) * 5000 + "\r\nkiwi\r\n").encode(encoding)
            self.assertEqual(self.hits("notes.txt", data), [("notes.txt", 2, digest("kiwi"))], encoding)

    def test_a_signed_binary_is_read_for_its_printable_and_utf16_ascii_runs(self):
        self.assertEqual(self.hits("docs/Icon.PNG", self.PNG), [])
        for name, signed in (("docs/Icon.PNG", self.PNG), ("instalador/tool.exe", b"MZ\x90\x00\x03\x00")):
            self.assertTrue(self.hits(name, signed + b"\x00\x07 a kiwi box \xff\x00"), name)
            for encoding in UTF16_ASCII_RUNS:
                self.assertTrue(self.hits(name, signed + "\x01 a Kiwi box ".encode(encoding) + b"\xff\xfe"), (name, encoding))
        self.assertEqual(self.hits("docs/Icon.PNG", self.PNG + b"\x00kiw\x00"), [])

    def test_model_weights_are_read_only_for_their_utf16_ascii_runs(self):
        weights = b"\x08\x08\x12\x07pytorch\x00"
        self.assertEqual(self.hits("modelos/model.onnx", weights + b"\x00\x07 a kiwi box \xff\x00"), [])
        self.assertEqual(self.hits("modelos/model.onnx", b"\x08\x08\x12\x04kiwi"), [])
        for encoding in UTF16_ASCII_RUNS:
            self.assertTrue(self.hits("modelos/model.onnx", weights + "\x01 a Kiwi box ".encode(encoding)), encoding)

    def test_a_file_without_its_signature_is_read_whole(self):
        self.assertEqual(self.hits("instalador/tool.exe", self.PNG + b" kiwi \n"), [("instalador/tool.exe", 3, digest("kiwi"))])
        self.assertEqual(self.hits("docs/note.png", b"one\nkiwi"), [("docs/note.png", 2, digest("kiwi"))])

    def test_the_scan_names_the_file(self):
        self.assertEqual(scan({"b.txt": b"kiwi", "a.txt": b"none", "c.md": b"x\nkiwi fruit"}, self.SINGLE | self.PAIR),
                         [("b.txt", 1, digest("kiwi")), ("c.md", 2, digest("kiwi")), ("c.md", 2, digest("kiwi fruit"))])


if __name__ == "__main__":
    unittest.main()

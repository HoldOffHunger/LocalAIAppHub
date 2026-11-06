class SqlValues:
    """Reads the rows out of one mysqldump INSERT line, honouring quotes and backslash escapes."""

    ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a"}

    def __init__(self, line: str):
        self.line = line
        self.at = line.index(" VALUES ") + len(" VALUES ")

    def rows(self):
        while self.at < len(self.line) and self.line[self.at] == "(":
            self.at += 1
            yield self._row()
            self.at += 1  # the comma between rows, or the closing semicolon

    def _row(self) -> list:
        values = []
        while True:
            values.append(self._value())
            closing = self.line[self.at]
            self.at += 1
            if closing == ")":
                return values

    def _value(self):
        if self.line[self.at] == "'":
            return self._string()
        end = self.at
        while self.line[end] not in ",)":
            end += 1
        raw, self.at = self.line[self.at:end], end
        return None if raw == "NULL" else raw

    def _string(self) -> str:
        out, self.at = [], self.at + 1
        while self.line[self.at] != "'":
            char = self.line[self.at]
            if char == "\\":
                self.at += 1
                char = self.ESCAPES.get(self.line[self.at], self.line[self.at])
            out.append(char)
            self.at += 1
        self.at += 1
        return "".join(out)

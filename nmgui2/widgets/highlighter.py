import re
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont


class NMHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:   f.setFontWeight(QFont.Weight.Bold)
            if italic: f.setFontItalic(True)
            return f

        # Record blocks — blue bold
        record_kw = (r'\$(PROB(?:LEM)?|DATA|INPUT|SUBROUTINES|MODEL|ABBR|'
                     r'PK|ERROR|DES|AES|PRED|MIX|INFN|'
                     r'THETA|OMEGA|SIGMA|'
                     r'EST(?:IMATION)?|COV(?:ARIANCE)?|SIM(?:ULATION)?|'
                     r'TABLE|SCATTER|SCAT|'
                     r'MSFI|THETAI|OMEGAI|SIGMAI|THETAP|OMEGAP|SIGMAP|'
                     r'PRIOR|LEVEL|CONTR|'
                     r'SIZE|BIND|ABBR)\b')

        # Fortran/NM control flow — yellow
        flow_kw = (r'\b(IF|THEN|ELSE|ELSEIF|ENDIF|END IF|'
                   r'DO|WHILE|ENDDO|END DO|'
                   r'CALL|RETURN|SUBROUTINE|FUNCTION|'
                   r'COMMON|DIMENSION|DOUBLE PRECISION|REAL|INTEGER|'
                   r'WRITE|READ|FORMAT|CONTINUE|EXIT|CYCLE)\b')

        # NM built-ins — cyan
        nm_builtins = (r'\b(EXP|LOG|SQRT|ABS|INT|MOD|MAX|MIN|SIGN|'
                       r'SIN|COS|TAN|ASIN|ACOS|ATAN|ATAN2|'
                       r'F|R|D|A|S|T|DADT|Y|W|IPRED|PRED|RES|WRES|'
                       r'THETA|ETA|ERR|EPS|DETA|IETA|PHI|LOG10)\b')

        # BLOCK / SAME / FIX keywords — orange
        block_kw = r'\b(BLOCK|SAME|DIAGONAL|FIX(?:ED)?|BAND|CHOLESKY|UNINT|VARIANCE|CORRELATION|SD)\b'

        self._rules = [
            (re.compile(record_kw, re.IGNORECASE),  fmt('#569cd6', bold=True)),
            (re.compile(flow_kw,   re.IGNORECASE),  fmt('#dcdcaa')),
            (re.compile(nm_builtins, re.IGNORECASE),fmt('#9cdcfe')),
            (re.compile(block_kw,  re.IGNORECASE),  fmt('#ce9178')),
            (re.compile(r';[^\n]*'),                 fmt('#6a9955', italic=True)),
            (re.compile(r'\b[-+]?\d*\.?\d+(?:[eEdD][+-]?\d+)?\b'), fmt('#b5cea8')),
            # Quoted strings
            (re.compile(r'"[^"]*"'),                 fmt('#ce9178')),
        ]

    def highlightBlock(self, text):
        for pat, fmt in self._rules:
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)

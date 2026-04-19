import re
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from ..app.theme import T


RECORD_KW = (r'\$(PROB(?:LEM)?|DATA|INPUT|SUBROUTINES|MODEL|ABBR|'
             r'PK|ERROR|DES|AES|PRED|MIX|INFN|'
             r'THETA|OMEGA|SIGMA|'
             r'EST(?:IMATION)?|COV(?:ARIANCE)?|SIM(?:ULATION)?|'
             r'TABLE|SCATTER|SCAT|'
             r'MSFI|THETAI|OMEGAI|SIGMAI|THETAP|OMEGAP|SIGMAP|'
             r'PRIOR|LEVEL|CONTR|'
             r'SIZE|BIND|ABBR)\b')
FLOW_KW = (r'\b(IF|THEN|ELSE|ELSEIF|ENDIF|END IF|'
           r'DO|WHILE|ENDDO|END DO|'
           r'CALL|RETURN|SUBROUTINE|FUNCTION|'
           r'COMMON|DIMENSION|DOUBLE PRECISION|REAL|INTEGER|'
           r'WRITE|READ|FORMAT|CONTINUE|EXIT|CYCLE)\b')
NM_BUILTINS = (r'\b(EXP|LOG|SQRT|ABS|INT|MOD|MAX|MIN|SIGN|'
               r'SIN|COS|TAN|ASIN|ACOS|ATAN|ATAN2|'
               r'F|R|D|A|S|T|DADT|Y|W|IPRED|PRED|RES|WRES|'
               r'THETA|ETA|ERR|EPS|DETA|IETA|PHI|LOG10)\b')
BLOCK_KW = r'\b(BLOCK|SAME|DIAGONAL|FIX(?:ED)?|BAND|CHOLESKY|UNINT|VARIANCE|CORRELATION|SD)\b'


def _fmt(color, bold=False, italic=False):
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class NMHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        self._rules = []
        self.rebuild_rules()

    def rebuild_rules(self):
        """Build syntax-color rules from the active theme. Call on theme switch
        and follow up with rehighlight() to repaint the document."""
        self._rules = [
            (re.compile(RECORD_KW,   re.IGNORECASE), _fmt(T('syn_record'),  bold=True)),
            (re.compile(FLOW_KW,     re.IGNORECASE), _fmt(T('syn_flow'))),
            (re.compile(NM_BUILTINS, re.IGNORECASE), _fmt(T('syn_builtin'))),
            (re.compile(BLOCK_KW,    re.IGNORECASE), _fmt(T('syn_block'))),
            (re.compile(r';[^\n]*'),                  _fmt(T('syn_comment'), italic=True)),
            (re.compile(r'\b[-+]?\d*\.?\d+(?:[eEdD][+-]?\d+)?\b'), _fmt(T('syn_number'))),
            (re.compile(r'"[^"]*"'),                  _fmt(T('syn_string'))),
        ]

    def highlightBlock(self, text):
        for pat, fmt in self._rules:
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)

"""
Fortran code printer

The FCodePrinter converts single sympy expressions into single Fortran
expressions, using the functions defined in the Fortran 77 standard where
possible. Some useful pointers to Fortran can be found on wikipedia:

http://en.wikipedia.org/wiki/Fortran

Most of the code below is based on the "Professional Programmer\'s Guide to
Fortran77" by Clive G. Page:

http://www.star.le.ac.uk/~cgp/prof77.html

Fortran is a case-insensitive language. This might cause trouble because sympy
is case sensitive. The implementation below does not care and leaves the
responsibility for generating properly cased Fortran code to the user.
"""


from str import StrPrinter
from sympy.printing.precedence import precedence
from sympy.core import S, Add, I, Symbol, Basic
from sympy.core.numbers import NumberSymbol
from sympy.functions import sin, cos, tan, asin, acos, atan, atan2, sinh, \
    cosh, tanh, sqrt, log, exp, abs, sign, conjugate, Piecewise
from sympy.utilities.iterables import postorder_traversal
from sympy.tensor import Idx


implicit_functions = set([
    sin, cos, tan, asin, acos, atan, atan2, sinh, cosh, tanh, sqrt, log, exp,
    abs, sign, conjugate
])


class FCodePrinter(StrPrinter):
    """A printer to convert sympy expressions to strings of Fortran code"""
    printmethod = "_fcode"

    _default_settings = {
        'order': None,
        'full_prec': 'auto',
        'assign_to': None,
        'precision': 15,
        'user_functions': {},
        'human': True,
        'source_format': 'fixed',
    }
    def __init__(self, settings=None):
        StrPrinter.__init__(self, settings)
        self._init_leading_padding()
        assign_to = self._settings['assign_to']
        if isinstance(assign_to, basestring):
            self._settings['assign_to'] = Symbol(assign_to)
        elif not isinstance(assign_to, (Basic, type(None))):
            raise TypeError("FCodePrinter cannot assign to object of type %s"%
                    type(assign_to))


    def _init_leading_padding(self):
        # leading columns depend on fixed or free format
        if self._settings['source_format'] == 'fixed':
            self._lead_code = "      "
            self._lead_cont = "     @ "
            self._lead_comment = "C     "
        elif self._settings['source_format'] == 'free':
            self._lead_code = ""
            self._lead_cont = "      "
            self._lead_comment = "! "
        else:
            raise ValueError(
                    "Unknown source format: %s" % self._settings['source_format']
                    )

    def _pad_leading_columns(self, lines):
        result = []
        for line in lines:
            if line.startswith('!'):
                result.append(self._lead_comment + line[1:].lstrip())
            else:
                result.append(self._lead_code + line)
        return result

    def _get_loop_opening_ending_ints(self, expr):
        """Returns a tuple (open_lines, close_lines) containing lists of codelines
        """

        indices = expr.atoms(Idx)
        # FIXME: sort indices in an optimized way
        open_lines = []
        close_lines = []
        local_ints = []

        for i in indices:
            # fortran arrays start at 1 and end at dimension
            open_lines.append("do %s = %s, %s" % (i.label, i.lower+1, i.upper+1))
            close_lines.append("end do")
            local_ints.append(i)
        return open_lines, close_lines, local_ints


    def doprint(self, expr):
        """Returns Fortran code for expr (as a string)"""
        # find all number symbols
        number_symbols = set([])
        for sub in postorder_traversal(expr):
            if isinstance(sub, NumberSymbol):
                number_symbols.add(sub)
        number_symbols = [(str(ns), ns.evalf(self._settings["precision"]))
                          for ns in sorted(number_symbols)]

        # keep a set of expressions that are not strictly translatable to
        # Fortran.
        self._not_fortran = set([])


        # Setup loops if expression contain Indexed objects
        openloop, closeloop, local_ints = self._get_loop_opening_ending_ints(expr)

        self._not_fortran |= set(local_ints)

        # the lhs may contain loops that are not in the rhs
        lhs = self._settings['assign_to']
        if lhs:
            open_lhs, close_lhs, lhs_ints = self._get_loop_opening_ending_ints(lhs)
            for n,ind in enumerate(lhs_ints):
                if ind not in self._not_fortran:
                    self._not_fortran.add(ind)
                    openloop.insert(0,open_lhs[n])
                    closeloop.append(close_lhs[n])
            lhs_printed = self._print(lhs)

        lines = []
        if isinstance(expr, Piecewise):
            # support for top-level Piecewise function
            for i, (e, c) in enumerate(expr.args):
                if i == 0:
                    lines.append("if (%s) then" % self._print(c))
                elif i == len(expr.args)-1 and c == True:
                    lines.append("else")
                else:
                    lines.append("else if (%s) then" % self._print(c))
                if self._settings["assign_to"] is None:
                    lines.extend(openloop)
                    lines.append("  %s" % self._print(e))
                    lines.extend(closeloop)
                else:
                    lines.extend(openloop)
                    lines.append("  %s = %s" % (lhs_printed, self._print(e)))
                    lines.extend(closeloop)
            lines.append("end if")
        else:
            lines.extend(openloop)
            line = StrPrinter.doprint(self, expr)
            if self._settings["assign_to"] is None:
                text = "%s" % line
            else:
                text = "%s = %s" % (lhs_printed, line)
            lines.append(text)
            lines.extend(closeloop)

        # format the output
        if self._settings["human"]:
            frontlines = []
            if len(self._not_fortran) > 0:
                frontlines.append("! Not Fortran:")
                for expr in sorted(self._not_fortran, key=self._print):
                    frontlines.append("! %s" % expr)
            for name, value in number_symbols:
                frontlines.append("parameter (%s = %s)" % (name, value))
            frontlines.extend(lines)
            lines = frontlines
            lines = self._pad_leading_columns(lines)
            lines = self._wrap_fortran(lines)
            lines = self.indent_code(lines)
            result = "\n".join(lines)
        else:
            lines = self._pad_leading_columns(lines)
            lines = self._wrap_fortran(lines)
            lines = self.indent_code(lines)
            result = number_symbols, self._not_fortran, "\n".join(lines)

        del self._not_fortran
        return result

    def _print_Add(self, expr):
        # purpose: print complex numbers nicely in Fortran.
        # collect the purely real and purely imaginary parts:
        pure_real = []
        pure_imaginary = []
        mixed = []
        for arg in expr.args:
            if arg.is_real and arg.is_number:
                pure_real.append(arg)
            elif arg.is_imaginary and arg.is_number:
                pure_imaginary.append(arg)
            else:
                mixed.append(arg)
        if len(pure_imaginary) > 0:
            if len(mixed) > 0:
                PREC = precedence(expr)
                term = Add(*mixed)
                t = self._print(term)
                if t.startswith('-'):
                    sign = "-"
                    t = t[1:]
                else:
                    sign = "+"
                if precedence(term) < PREC:
                    t = "(%s)" % t

                return "cmplx(%s,%s) %s %s" % (
                    self._print(Add(*pure_real)),
                    self._print(-I*Add(*pure_imaginary)),
                    sign, t,
                )
            else:
                return "cmplx(%s,%s)" % (
                    self._print(Add(*pure_real)),
                    self._print(-I*Add(*pure_imaginary)),
                )
        else:
            return StrPrinter._print_Add(self, expr)

    def _print_Function(self, expr):
        name = self._settings["user_functions"].get(expr.__class__)
        if name is None:
            if expr.func == conjugate:
                name = "conjg"
            else:
                name = expr.func.__name__
            if expr.func not in implicit_functions:
                self._not_fortran.add(expr)
        return "%s(%s)" % (name, self.stringify(expr.args, ", "))

    _print_Factorial = _print_Function

    def _print_ImaginaryUnit(self, expr):
        # purpose: print complex numbers nicely in Fortran.
        return "cmplx(0,1)"

    def _print_int(self, expr):
        return str(expr)

    def _print_Mul(self, expr):
        # purpose: print complex numbers nicely in Fortran.
        if expr.is_imaginary and expr.is_number:
            return "cmplx(0,%s)" % (
                self._print(-I*expr)
            )
        else:
            return StrPrinter._print_Mul(self, expr)

    def _print_NumberSymbol(self, expr):
        # Standard Fortran has no predefined constants. Write their string
        # representation, and assume parameter statements are defined elsewhere
        # in the code to make this work.
        return str(expr)

    _print_Catalan = _print_NumberSymbol
    _print_EulerGamma = _print_NumberSymbol
    _print_Exp1 = _print_NumberSymbol
    _print_GoldenRatio = _print_NumberSymbol
    _print_Pi = _print_NumberSymbol

    def _print_Pow(self, expr):
        PREC = precedence(expr)
        if expr.exp is S.NegativeOne:
            return '1.0/%s'%(self.parenthesize(expr.base, PREC))
        elif expr.exp == 0.5:
            return 'sqrt(%s)' % self._print(expr.base)
        else:
            return StrPrinter._print_Pow(self, expr)

    def _print_Rational(self, expr):
        p, q = int(expr.p), int(expr.q)
        return '%d.0/%d.0' % (p, q)

    def _print_not_fortran(self, expr):
        self._not_fortran.add(expr)
        return self.emptyPrinter(expr)

    # The following can not be simply translated into Fortran.
    _print_Basic = _print_not_fortran
    _print_ComplexInfinity = _print_not_fortran
    _print_Derivative = _print_not_fortran
    _print_dict = _print_not_fortran
    _print_Dummy = _print_not_fortran
    _print_ExprCondPair = _print_not_fortran
    _print_GeometryEntity = _print_not_fortran
    _print_Infinity = _print_not_fortran
    _print_Integral = _print_not_fortran
    _print_Interval = _print_not_fortran
    _print_Limit = _print_not_fortran
    _print_list = _print_not_fortran
    _print_Matrix = _print_not_fortran
    _print_DeferredVector = _print_not_fortran
    _print_NaN = _print_not_fortran
    _print_NegativeInfinity = _print_not_fortran
    _print_Normal = _print_not_fortran
    _print_Order = _print_not_fortran
    _print_PDF = _print_not_fortran
    _print_RootOf = _print_not_fortran
    _print_RootsOf = _print_not_fortran
    _print_RootSum = _print_not_fortran
    _print_Sample = _print_not_fortran
    _print_SMatrix = _print_not_fortran
    _print_tuple = _print_not_fortran
    _print_Uniform = _print_not_fortran
    _print_Unit = _print_not_fortran
    _print_Wild = _print_not_fortran
    _print_WildFunction = _print_not_fortran

    def _wrap_fortran(self, lines):
        """Wrap long Fortran lines

           Argument:
             lines  --  a list of lines (without \\n character)

           A comment line is split at white space. Code lines are split with a more
           complex rule to give nice results.
        """
        # routine to find split point in a code line
        my_alnum = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
        my_white = set(" \t()")
        def split_pos_code(line, endpos):
            if len(line) <= endpos:
                return len(line)
            pos = endpos
            split = lambda pos: \
                (line[pos] in my_alnum and line[pos-1] not in my_alnum) or \
                (line[pos] not in my_alnum and line[pos-1] in my_alnum) or \
                (line[pos] in my_white and line[pos-1] not in my_white) or \
                (line[pos] not in my_white and line[pos-1] in my_white)
            while not split(pos):
                pos -= 1
                if pos == 0:
                    return endpos
            return pos
        # split line by line and add the splitted lines to result
        result = []
        if self._settings['source_format'] == 'free':
            trailing = ' &'
        else:
            trailing = ''
        for line in lines:
            if line.startswith(self._lead_comment):
                # comment line
                if len(line) > 72:
                    pos = line.rfind(" ", 6, 72)
                    if pos == -1:
                        pos = 72
                    hunk = line[:pos]
                    line = line[pos:].lstrip()
                    result.append(hunk)
                    while len(line) > 0:
                        pos = line.rfind(" ", 0, 66)
                        if pos == -1 or len(line) < 66:
                            pos = 66
                        hunk = line[:pos]
                        line = line[pos:].lstrip()
                        result.append("%s%s" % (self._lead_comment, hunk))
                else:
                    result.append(line)
            elif line.startswith(self._lead_code):
                # code line
                pos = split_pos_code(line, 72)
                hunk = line[:pos].rstrip()
                line = line[pos:].lstrip()
                if line: hunk += trailing
                result.append(hunk)
                while len(line) > 0:
                    pos = split_pos_code(line, 65)
                    hunk = line[:pos].rstrip()
                    line = line[pos:].lstrip()
                    if line: hunk += trailing
                    result.append("%s%s" % (self._lead_cont, hunk))
            else:
                result.append(line)
        return result

    def indent_code(self, code):
        """Accepts a string of code or a list of code lines
        """
        if self._settings['source_format'] == 'fixed':
            return code
        if isinstance(code, basestring):
            code_lines = self.indent_code(code.splitlines())
            return '\n'.join(code_lines)

        code = [ line.lstrip() for line in code ]

        inc_keyword = ('do ', 'if(', 'if ', 'do\n')
        dec_keyword = ('end ', 'enddo', 'end\n')

        increase = [ int(reduce(lambda x, y: x or line.startswith(y),
                                inc_keyword, False)) \
                     for line in code ]
        decrease = [ int(reduce(lambda x, y: x or line.startswith(y),
                                dec_keyword, False)) \
                     for line in code ]
        continuation = [ line[-1] == '&' for line in code ]

        level = 0
        cont_padding = 0
        tabwidth = 3
        new_code = []
        for i in range(len(code)):
            level -= decrease[i]
            padding = " "*(level*tabwidth + cont_padding)
            new_code.append("%s%s" % (padding, code[i]))

            if continuation[i]:
                cont_padding = 2*tabwidth
            else:
                cont_padding = 0
            level += increase[i]
        return new_code

def fcode(expr, **settings):
    """Converts an expr to a string of Fortran 77 code

       Arguments:
         expr  --  a sympy expression to be converted

       Optional arguments:
         assign_to  --  When given, the argument is used as the name of the
                        variable to which the Fortran expression is assigned.
                        (This is helpful in case of line-wrapping.)
         precision  --  the precision for numbers such as pi [default=15]
         user_functions  --  A dictionary where keys are FunctionClass instances
                             and values are there string representations.
         human  --  If True, the result is a single string that may contain
                    some parameter statements for the number symbols. If
                    False, the same information is returned in a more
                    programmer-friendly data structure.
         source_format  --  The source format can be either 'fixed' or 'free'.
                            [default='fixed']

       >>> from sympy import fcode, symbols, Rational, pi, sin
       >>> x, tau = symbols(["x", "tau"])
       >>> fcode((2*tau)**Rational(7,2))
       '      8*sqrt(2)*tau**(7.0/2.0)'
       >>> fcode(sin(x), assign_to="s")
       '      s = sin(x)'
       >>> print fcode(pi)
             parameter (pi = 3.14159265358979)
             pi

    """
    # run the printer
    printer = FCodePrinter(settings)
    return printer.doprint(expr)


def print_fcode(expr, **settings):
    """Prints the Fortran representation of the given expression.

       See fcode for the meaning of the optional arguments.
    """
    print fcode(expr, **settings)


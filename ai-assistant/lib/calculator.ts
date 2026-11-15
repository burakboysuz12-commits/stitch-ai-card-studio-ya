/**
 * Safe arithmetic evaluator (recursive-descent parser). No `eval`, no `Function`.
 *
 * Grammar:
 *   expression := term (('+' | '-') term)*
 *   term       := unary (('*' | '/' | '%') unary)*
 *   unary      := ('+' | '-') unary | power
 *   power      := postfix ('^' unary)?          (right-associative)
 *   postfix    := primary '!'*
 *   primary    := number | constant | func '(' args ')' | '(' expression ')'
 */

type Token =
  | { kind: 'number'; value: number }
  | { kind: 'ident'; value: string }
  | { kind: 'op'; value: string };

const FUNCTIONS: Readonly<Record<string, { arity: [number, number]; fn: (...args: number[]) => number }>> = {
  sqrt: { arity: [1, 1], fn: Math.sqrt },
  cbrt: { arity: [1, 1], fn: Math.cbrt },
  abs: { arity: [1, 1], fn: Math.abs },
  sin: { arity: [1, 1], fn: Math.sin },
  cos: { arity: [1, 1], fn: Math.cos },
  tan: { arity: [1, 1], fn: Math.tan },
  asin: { arity: [1, 1], fn: Math.asin },
  acos: { arity: [1, 1], fn: Math.acos },
  atan: { arity: [1, 1], fn: Math.atan },
  exp: { arity: [1, 1], fn: Math.exp },
  ln: { arity: [1, 1], fn: Math.log },
  log2: { arity: [1, 1], fn: Math.log2 },
  log: {
    arity: [1, 2],
    fn: (x: number, base?: number) => (base === undefined ? Math.log10(x) : Math.log(x) / Math.log(base)),
  },
  floor: { arity: [1, 1], fn: Math.floor },
  ceil: { arity: [1, 1], fn: Math.ceil },
  round: {
    arity: [1, 2],
    fn: (x: number, digits?: number) => {
      const f = 10 ** (digits ?? 0);
      return Math.round(x * f) / f;
    },
  },
  min: { arity: [1, 50], fn: Math.min },
  max: { arity: [1, 50], fn: Math.max },
  pow: { arity: [2, 2], fn: Math.pow },
};

const CONSTANTS: Readonly<Record<string, number>> = { pi: Math.PI, e: Math.E, tau: 2 * Math.PI };

const NUMBER_RE = /^(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?/i;
const IDENT_RE = /^[a-z_][a-z0-9_]*/i;
const OPERATORS = new Set(['+', '-', '*', '/', '^', '%', '(', ')', ',', '!']);

function tokenize(input: string): Token[] {
  const src = input.replace(/×/g, '*').replace(/÷/g, '/').replace(/\*\*/g, '^').replace(/−/g, '-');
  const tokens: Token[] = [];
  let i = 0;
  while (i < src.length) {
    const ch = src[i] ?? '';
    if (/\s/.test(ch)) {
      i += 1;
      continue;
    }
    const rest = src.slice(i);
    const num = NUMBER_RE.exec(rest);
    if (num) {
      tokens.push({ kind: 'number', value: Number(num[0]) });
      i += num[0].length;
      continue;
    }
    const ident = IDENT_RE.exec(rest);
    if (ident) {
      tokens.push({ kind: 'ident', value: ident[0].toLowerCase() });
      i += ident[0].length;
      continue;
    }
    if (OPERATORS.has(ch)) {
      tokens.push({ kind: 'op', value: ch });
      i += 1;
      continue;
    }
    throw new Error(`Unexpected character "${ch}" at position ${i + 1}.`);
  }
  return tokens;
}

function factorial(n: number): number {
  if (!Number.isInteger(n) || n < 0) throw new Error('Factorial is only defined for non-negative integers.');
  if (n > 170) throw new Error('Factorial argument too large.');
  let r = 1;
  for (let k = 2; k <= n; k += 1) r *= k;
  return r;
}

class Parser {
  private pos = 0;
  private readonly tokens: readonly Token[];

  constructor(tokens: readonly Token[]) {
    this.tokens = tokens;
  }

  parse(): number {
    if (this.tokens.length === 0) throw new Error('Expression is empty.');
    const value = this.expression();
    const leftover = this.peek();
    if (leftover) throw new Error(`Unexpected token "${String(leftover.value)}".`);
    return value;
  }

  private peek(): Token | undefined {
    return this.tokens[this.pos];
  }

  private isOp(value: string): boolean {
    const t = this.peek();
    return t?.kind === 'op' && t.value === value;
  }

  private expectOp(value: string): void {
    if (!this.isOp(value)) throw new Error(`Expected "${value}".`);
    this.pos += 1;
  }

  private expression(): number {
    let value = this.term();
    while (this.isOp('+') || this.isOp('-')) {
      const op = this.tokens[this.pos++]?.value;
      const rhs = this.term();
      value = op === '+' ? value + rhs : value - rhs;
    }
    return value;
  }

  private term(): number {
    let value = this.unary();
    while (this.isOp('*') || this.isOp('/') || this.isOp('%')) {
      const op = this.tokens[this.pos++]?.value;
      const rhs = this.unary();
      if ((op === '/' || op === '%') && rhs === 0) throw new Error('Division by zero.');
      value = op === '*' ? value * rhs : op === '/' ? value / rhs : value % rhs;
    }
    return value;
  }

  private unary(): number {
    if (this.isOp('-')) {
      this.pos += 1;
      return -this.unary();
    }
    if (this.isOp('+')) {
      this.pos += 1;
      return this.unary();
    }
    return this.power();
  }

  private power(): number {
    const base = this.postfix();
    if (this.isOp('^')) {
      this.pos += 1;
      return base ** this.unary();
    }
    return base;
  }

  private postfix(): number {
    let value = this.primary();
    while (this.isOp('!')) {
      this.pos += 1;
      value = factorial(value);
    }
    return value;
  }

  private primary(): number {
    const token = this.tokens[this.pos];
    if (!token) throw new Error('Unexpected end of expression.');

    if (token.kind === 'number') {
      this.pos += 1;
      return token.value;
    }

    if (token.kind === 'ident') {
      this.pos += 1;
      if (this.isOp('(')) {
        const def = FUNCTIONS[token.value];
        if (!def) throw new Error(`Unknown function "${token.value}".`);
        this.pos += 1;
        const args: number[] = [];
        if (!this.isOp(')')) {
          args.push(this.expression());
          while (this.isOp(',')) {
            this.pos += 1;
            args.push(this.expression());
          }
        }
        this.expectOp(')');
        const [minArgs, maxArgs] = def.arity;
        if (args.length < minArgs || args.length > maxArgs) {
          throw new Error(`Function "${token.value}" expects ${minArgs === maxArgs ? minArgs : `${minArgs}-${maxArgs}`} argument(s).`);
        }
        return def.fn(...args);
      }
      const constant = CONSTANTS[token.value];
      if (constant === undefined) throw new Error(`Unknown identifier "${token.value}".`);
      return constant;
    }

    if (token.value === '(') {
      this.pos += 1;
      const value = this.expression();
      this.expectOp(')');
      return value;
    }

    throw new Error(`Unexpected token "${token.value}".`);
  }
}

export interface CalculationResult {
  expression: string;
  result: number;
  formatted: string;
}

export function evaluateExpression(expression: string): CalculationResult {
  const raw = new Parser(tokenize(expression)).parse();
  if (!Number.isFinite(raw)) throw new Error('Result is not a finite number.');
  // Remove binary floating-point noise, e.g. 0.1 + 0.2 -> 0.3
  const result = Number.parseFloat(raw.toPrecision(15));
  return {
    expression,
    result,
    formatted: result.toLocaleString('en-US', { maximumFractionDigits: 10 }),
  };
}

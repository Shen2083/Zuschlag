/**
 * Exact decimal arithmetic for money and quantities.
 *
 * The API sends every amount as a decimal string (Python `Decimal`). Floats
 * would turn 0.1 + 0.2 into 0.30000000000000004, so live recalculation in the
 * browser uses scaled BigInts and the same commercial rounding as the server
 * (`ROUND_HALF_UP`: halves round away from zero).
 */
export type DecimalLike = Dec | string | number | bigint;

const DECIMAL = /^([+-])?(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/;

export class Dec {
  private constructor(
    /** value = units / 10^scale */
    readonly units: bigint,
    readonly scale: number,
  ) {}

  static readonly ZERO = new Dec(0n, 0);

  static from(value: DecimalLike): Dec {
    if (value instanceof Dec) return value;
    if (typeof value === "bigint") return new Dec(value, 0);
    if (typeof value === "number") {
      if (!Number.isFinite(value)) throw new RangeError(`not a finite number: ${value}`);
      value = String(value);
    }
    const m = DECIMAL.exec(value.trim());
    if (!m || (m[2] === "" && (m[3] ?? "") === "")) {
      throw new SyntaxError(`not a decimal: "${value}"`);
    }
    const [, sign, int = "", frac = "", exp] = m;
    let units = BigInt((int || "0") + frac);
    let scale = frac.length - (exp ? Number(exp) : 0);
    if (scale < 0) {
      units *= 10n ** BigInt(-scale);
      scale = 0;
    }
    return new Dec(sign === "-" ? -units : units, scale);
  }

  static tryFrom(value: DecimalLike | null | undefined): Dec | null {
    if (value === null || value === undefined || value === "") return null;
    try {
      return Dec.from(value);
    } catch {
      return null;
    }
  }

  static sum(values: Iterable<DecimalLike>): Dec {
    let total = Dec.ZERO;
    for (const v of values) total = total.add(v);
    return total;
  }

  private rescale(scale: number): bigint {
    return this.units * 10n ** BigInt(scale - this.scale);
  }

  add(other: DecimalLike): Dec {
    const o = Dec.from(other);
    const scale = Math.max(this.scale, o.scale);
    return new Dec(this.rescale(scale) + o.rescale(scale), scale);
  }

  sub(other: DecimalLike): Dec {
    return this.add(Dec.from(other).neg());
  }

  neg(): Dec {
    return new Dec(-this.units, this.scale);
  }

  mul(other: DecimalLike): Dec {
    const o = Dec.from(other);
    return new Dec(this.units * o.units, this.scale + o.scale);
  }

  /** Exact division by 10^n (e.g. percent: `.shift(2)` divides by 100). */
  shift(n: number): Dec {
    return new Dec(this.units, this.scale + n);
  }

  /** Round to `places` decimals, halves away from zero (Python ROUND_HALF_UP). */
  quantize(places: number): Dec {
    if (places >= this.scale) return new Dec(this.rescale(places), places);
    const divisor = 10n ** BigInt(this.scale - places);
    const negative = this.units < 0n;
    const abs = negative ? -this.units : this.units;
    let q = abs / divisor;
    if ((abs % divisor) * 2n >= divisor) q += 1n;
    return new Dec(negative ? -q : q, places);
  }

  cmp(other: DecimalLike): -1 | 0 | 1 {
    const o = Dec.from(other);
    const scale = Math.max(this.scale, o.scale);
    const a = this.rescale(scale);
    const b = o.rescale(scale);
    return a < b ? -1 : a > b ? 1 : 0;
  }

  eq(other: DecimalLike): boolean {
    return this.cmp(other) === 0;
  }

  isZero(): boolean {
    return this.units === 0n;
  }

  isNegative(): boolean {
    return this.units < 0n;
  }

  /** Plain string with exactly `places` decimals (rounded), or as stored. */
  toFixed(places?: number): string {
    const d = places === undefined ? this : this.quantize(places);
    const negative = d.units < 0n;
    const digits = (negative ? -d.units : d.units).toString().padStart(d.scale + 1, "0");
    const int = digits.slice(0, digits.length - d.scale);
    const frac = d.scale ? `.${digits.slice(-d.scale)}` : "";
    return `${negative ? "-" : ""}${int}${frac}`;
  }

  /** Canonical string without trailing zeros ("12.50" -> "12.5"). */
  toString(): string {
    const s = this.toFixed();
    return s.includes(".") ? s.replace(/\.?0+$/, "") : s;
  }

  /** For sliders and charts only, never for money arithmetic. */
  toNumber(): number {
    return Number(this.toFixed());
  }
}

export const dec = Dec.from;

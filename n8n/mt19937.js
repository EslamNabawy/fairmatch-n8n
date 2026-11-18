// CPython-compatible Mersenne Twister (matches random.Random(int seed)).
function MT19937(seed) {
  const N = 624, M = 397, A = 0x9908b0df;
  const mt = new Array(N);
  const key = [];
  let x = Math.floor(seed);
  if (!(x > 0)) key.push(0);
  while (x > 0) { key.push(x % 0x100000000); x = Math.floor(x / 0x100000000); }
  mt[0] = 19650218 >>> 0;
  for (let i = 1; i < N; i++) {
    mt[i] = (Math.imul(1812433253, mt[i - 1] ^ (mt[i - 1] >>> 30)) + i) >>> 0;
  }
  let ii = 1, jj = 0;
  const kk = Math.max(N, key.length);
  for (let c = 0; c < kk; c++) {
    mt[ii] = (mt[ii] ^ Math.imul(mt[ii - 1] ^ (mt[ii - 1] >>> 30), 1664525)) >>> 0;
    mt[ii] = (mt[ii] + key[jj] + jj) >>> 0;
    ii++; jj++;
    if (ii >= N) { mt[0] = mt[N - 1]; ii = 1; }
    if (jj >= key.length) jj = 0;
  }
  for (let c = 0; c < N - 1; c++) {
    mt[ii] = (mt[ii] ^ Math.imul(mt[ii - 1] ^ (mt[ii - 1] >>> 30), 1566083941)) >>> 0;
    mt[ii] = (mt[ii] - ii) >>> 0;
    ii++;
    if (ii >= N) { mt[0] = mt[N - 1]; ii = 1; }
  }
  mt[0] = 0x80000000;
  let mti = N;
  const twist = () => {
    for (let i = 0; i < N; i++) {
      const y = (mt[i] & 0x80000000) + (mt[(i + 1) % N] & 0x7fffffff);
      mt[i] = (mt[(i + M) % N] ^ (y >>> 1) ^ ((y & 1) ? A : 0)) >>> 0;
    }
    mti = 0;
  };
  const int32 = () => {
    if (mti >= N) twist();
    let y = mt[mti++];
    y ^= y >>> 11;
    y ^= (y << 7) & 0x9d2c5680;
    y ^= (y << 15) & 0xefc60000;
    y ^= y >>> 18;
    return y >>> 0;
  };
  const random = () => ((int32() >>> 5) * 67108864.0 + (int32() >>> 6)) / 9007199254740992.0;
  const getrandbits = k => {
    let r = 0, rem = k;
    while (rem > 0) {
      const take = Math.min(32, rem);
      r = r * Math.pow(2, take) + (int32() >>> (32 - take));
      rem -= take;
    }
    return r;
  };
  const randbelow = n => {
    if (!(n > 0)) throw new Error('randbelow: empty range');
    const k = n.toString(2).length;
    let r = getrandbits(k);
    while (r >= n) r = getrandbits(k);
    return r;
  };
  const shuffle = arr => {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = randbelow(i + 1);
      const t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  };
  return { random, shuffle, randbelow, int32 };
}
if (typeof module !== 'undefined') module.exports = MT19937;

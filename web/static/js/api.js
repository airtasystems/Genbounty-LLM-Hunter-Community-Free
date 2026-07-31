/**
 * Genbounty HTTP helpers (no Vue dependency).
 */
(function (G) {
  'use strict';

  const API = '';

  G.api = async function api(path, opts) {
    const res = await fetch(API + path, opts);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  };

  G.isAbortError = function isAbortError(err) {
    return Boolean(err && (err.name === 'AbortError' || err.code === 20));
  };
})(window.Genbounty = window.Genbounty || {});

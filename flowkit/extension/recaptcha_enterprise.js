(function () {
  var w = window,
    C = '___grecaptcha_cfg',
    cfg = (w[C] = w[C] || {}),
    N = 'grecaptcha';
  var E = 'enterprise',
    a = (w[N] = w[N] || {}),
    gr = (a[E] = a[E] || {});
  gr.ready =
    gr.ready ||
    function (f) {
      (cfg['fns'] = cfg['fns'] || []).push(f);
    };
  w['__recaptcha_api'] = 'https://www.google.com/recaptcha/enterprise/';
  (cfg['enterprise'] = cfg['enterprise'] || []).push(true);
  (cfg['render'] = cfg['render'] || []).push('explicit');
  (cfg['render'] = cfg['render'] || []).push('6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV');
  (cfg['anchor-ms'] = cfg['anchor-ms'] || []).push(20000);
  (cfg['execute-ms'] = cfg['execute-ms'] || []).push(30000);
  w['__google_recaptcha_client'] = true;

  // Note: recaptcha__en.js is loaded directly in the page's MAIN world via
  // manifest.json content_scripts. Dynamically creating a <script> element with
  // a string .src is blocked by flow.google.com's TrustedScriptURL CSP policy.
})();
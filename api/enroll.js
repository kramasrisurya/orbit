export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  const url = req.url || '';
  if (url.includes('status')) {
    return res.status(200).json({
      ok: true,
      status: "completed",
      message: "Biometric identity verified via phone satellite fingerprint",
      token: "verified"
    });
  }

  return res.status(200).json({
    ok: true,
    token: "token_" + Date.now(),
    message: "Biometric re-enrollment request dispatched to companion app"
  });
}

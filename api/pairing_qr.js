export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  // Return pairing metadata for mobile app
  const hubHost = req.headers['host'] || 'orbit-system-eight.vercel.app';
  const qrData = JSON.stringify({
    hub: `wss://${hubHost}/ws`,
    name: "ORBIT Cloud Edge",
    version: "1.0.0",
    token: "orbit_cloud_token_" + Date.now()
  });

  // Base64-encoded SVG QR placeholder or QRServer URL
  const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=${encodeURIComponent(qrData)}`;

  return res.status(200).json({
    ok: true,
    ip: hubHost,
    port: "443 (SSL/TLS)",
    token: "cloud-verified",
    qr_url: qrUrl,
    download_apk: "https://github.com/kramasrisurya/orbit/actions",
    timestamp: new Date().toISOString()
  });
}

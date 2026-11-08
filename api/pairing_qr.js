export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  const ip = (req.query && req.query.ip) ? req.query.ip : '10.100.231.12';
  const key = "GqAv+w1AhVw1lujOWX5SqCu0j/RltwbkrYPs2tBJfZM=";
  const qrData = JSON.stringify({
    key: key,
    ip: ip,
    port: 8765
  });

  const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=${encodeURIComponent(qrData)}`;

  return res.status(200).json({
    ok: true,
    key: key,
    ip: ip,
    port: 8765,
    qr_url: qrUrl,
    download_apk: "https://github.com/kramasrisurya/orbit/actions",
    timestamp: new Date().toISOString()
  });
}

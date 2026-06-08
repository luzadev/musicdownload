/**
 * Invio email transazionali via Resend (https://resend.com).
 * Usa fetch nativo di Node >= 20 — nessuna dipendenza.
 *
 * Variabili env richieste:
 *   RESEND_API_KEY     dal dashboard Resend
 *   EMAIL_FROM         "MusicTools <noreply@djluza.com>" (dominio verificato)
 */

const FROM = process.env.EMAIL_FROM || "MusicTools <noreply@djluza.com>";
const BASE = process.env.PUBLIC_BASE_URL || "https://musictools.djluza.com";

export async function sendLicenseEmail(to, licenseKey) {
  if (!process.env.RESEND_API_KEY) {
    console.warn("[email] RESEND_API_KEY non impostata, skip invio a", to);
    return;
  }

  const q = `key=${encodeURIComponent(licenseKey)}&email=${encodeURIComponent(to)}`;
  const macUrl = `${BASE}/api/download/macos?${q}`;
  const winUrl = `${BASE}/api/download/windows?${q}`;

  const html = `
    <div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#111">
      <h1 style="color:#1db954;margin:0 0 14px;font-size:22px">Grazie per aver scelto MusicTools!</h1>
      <p style="font-size:15px;line-height:1.55;margin:0 0 18px">
        Ecco la tua chiave di licenza. Conservala con cura — ti servira' per attivare l'app.
      </p>
      <p style="font-size:22px;letter-spacing:2px;font-family:monospace;background:#f4f4f4;padding:16px;border-radius:10px;text-align:center;margin:0 0 24px;color:#000">
        ${licenseKey}
      </p>

      <p style="font-size:15px;margin:0 0 12px"><strong>Scarica l'app:</strong></p>
      <table cellpadding="0" cellspacing="0" border="0" style="margin:0 0 24px">
        <tr>
          <td style="padding-right:10px">
            <a href="${macUrl}" style="display:inline-block;background:#1db954;color:#fff;text-decoration:none;padding:12px 22px;border-radius:999px;font-weight:700;font-size:14px">
              🍎 Scarica per Mac
            </a>
          </td>
          <td>
            <a href="${winUrl}" style="display:inline-block;background:#1db954;color:#fff;text-decoration:none;padding:12px 22px;border-radius:999px;font-weight:700;font-size:14px">
              🪟 Scarica per Windows
            </a>
          </td>
        </tr>
      </table>

      <p style="font-size:15px;margin:0 0 8px"><strong>Come attivare:</strong></p>
      <ol style="font-size:14.5px;line-height:1.6;padding-left:22px">
        <li>Clicca uno dei bottoni qui sopra per scaricare l'installer</li>
        <li>Installa l'app (su Mac: tasto destro → Apri → Apri; su Windows: Esegui comunque)</li>
        <li>Apri MusicTools: la prima schermata ti chiede email e chiave</li>
        <li>Inserisci <strong>${to}</strong> e la chiave qui sopra</li>
      </ol>
      <p style="font-size:14px;color:#555;margin:18px 0 0">Puoi attivare la licenza fino a 3 dispositivi (Mac e Windows mixati).</p>
      <p style="font-size:13px;color:#888;margin:8px 0 0">
        Hai bisogno di riscaricare in futuro? Vai su <a href="${BASE}/download" style="color:#1db954">${BASE.replace(/^https?:\/\//, "")}/download</a> e inserisci email + chiave.
      </p>
      <hr style="border:none;border-top:1px solid #eee;margin:28px 0"/>
      <p style="color:#666;font-size:12px;margin:0">Hai problemi? Scrivici a <a href="mailto:info@djluza.com">info@djluza.com</a></p>
    </div>
  `;

  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${process.env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: FROM,
      to: [to],
      subject: "La tua licenza MusicTools",
      html,
    }),
  });

  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`Resend ${resp.status}: ${txt}`);
  }
}

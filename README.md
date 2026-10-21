# Current status: direct public X HTML scraper

The experimental scraper now works without Chromium, Playwright, login cookies,
RSS.app, or X developer API. It uses urllib with the existing HTTPS proxy and CA
verification to read https://x.com/thsottiaux, then decodes JSON strings already
embedded in script tags. No page JavaScript is executed and no private API is called.

Live validation returned 5 posts, including Day 15 reset and the full long-form
usage correction post. Only Tibo-authored timeline posts are retained; nested
quotes are excluded. Long-form note text overrides abbreviated text. If expanded
text is required but missing, the post is skipped instead of silently truncated.

Read-only workflow:

```sh
cd /workspace/tibo-notif
python -m unittest -q
python scrape_x.py
JUDGE_MODEL=gemini-3.5-flash-lite python monitor_judge.py
JUDGE_MODEL=gemini-3.5-flash-lite python -u monitor_judge.py --loop
```

Monitor polls every 600 seconds, filters reset/resets mentions, then passes entire
extracted text to Gemini. First run considers newest post only; subsequent newer
posts enter a persistent queue. At most one candidate is judged per cycle. Cached
judgments do not consume an API request. Default 15 attempted calls per Pacific
calendar day, 256 output tokens and 4000 input characters. Failures count toward
budget; oversized posts are not silently truncated. Project quota can be consumed
by other applications too. Existing gemini_api_key is reused. No Fonnte sender is
imported or called by the experimental monitor. It is still a read-only workflow.

Live Gemini 3.5 Flash-Lite classified Day 15 as reset with exact evidence
"and reset. Enjoy.". A live source poll skipped newest Day 16 because it contains
no reset mention. 30 local tests passed. No WhatsApp was sent by these checks.

Limits: public HTML can change or become inaccessible; only the visible public
page is read, with no pagination/reply coverage guarantee. No images or additional
thread context. Empty or changed page data causes an explicit error. Live processes
still depend on the cloud environment staying active. Preserve .local/ state.

The earlier RSS bot and its database remain separate. Historical implementation
notes below describe previous versions and failures, superseded by this section.

---

# Tibo Notif

Bot Python 3.12+ tanpa dependency tambahan. Pantau postingan dan balasan
@thsottiaux lewat RSS (default) atau X API v2, cari kandidat pengumuman reset limit Codex,
dan kirim link postingan lewat Fonnte.

## Konfigurasi aman

Isi lewat environment settings, jangan commit token atau kirim ke chat:

- `SOURCE`: default `rss`; gunakan `x` hanya jika ingin API resmi X.
- `RSS_FEED_URL`: URL RSS/XML HTTPS untuk akun @thsottiaux.
  Buat feed di https://rss.app/rss-feed/create-twitter-rss-feed dengan URL
  https://x.com/thsottiaux, lalu salin URL feed yang dihasilkan (bukan halaman profil).
  Jika URL berisi token privat, isi hanya lewat environment settings.
- `X_BEARER_TOKEN`: hanya diperlukan untuk `SOURCE=x`, tidak dipakai mode RSS.
- `FONNTE_TOKEN`: API token device Fonnte; isi sebagai secret di environment settings.
  Hubungkan device WhatsApp di dashboard Fonnte terlebih dahulu.
- `WHATSAPP_TO`: nomor tujuan internasional, misalnya 62812..., tanpa +.
- `POLL_SECONDS`: default 300, minimum 60; sesuaikan kuota X API.
- `STATE_PATH`: default `.local/state.sqlite3`; simpan file ini untuk resume.

Destinasi HTTPS: host URL RSS (misalnya `rss.app`) dan `api.fonnte.com`.
`api.x.com` hanya dipakai mode X. Host feed dan redirect perlu diizinkan di network settings.
Gunakan nomor tujuan milik sendiri atau penerima yang setuju menerima notifikasi.
Konfigurasi Meta, phone number ID, dan template WhatsApp tidak dipakai lagi.
Hapus requirement Meta lama di environment settings jika masih tampil.

## Jalankan di Codex Cloud

Gunakan checkout yang sudah ada; tidak perlu worktree baru.

```sh
cd /workspace/tibo-notif
python -m unittest -v
python bot.py --demo     # offline, tidak mengirim WA
python bot.py --check-feed # baca RSS, tanpa WA/token X/perubahan state
python bot.py --once     # live: satu poll, bisa mengirim WA
python bot.py            # live: loop sampai dihentikan dengan Ctrl+C
```

Tidak perlu instal paket. `--once` dan loop live memerlukan semua konfigurasi.
Untuk proses background, arahkan stdout/stderr ke `.local/bot.log` dan simpan
PID agar hanya proses milik bot ini yang dihentikan. File lock mencegah dua
instance memakai state yang sama. Proses hidup tidak dipulihkan otomatis saat
Codex Cloud berhenti; environment ini tidak menjamin layanan 24/7.

## Perilaku dan batasan

- Poll pertama dapat mengirim notifikasi postingan lama yang ada di feed.
- Mode RSS membaca ulang semua item yang tersedia supaya postingan yang masuk
  terlambat tidak terlewat. ID postingan yang sudah dikirim disimpan di SQLite.
  Mode X menggunakan `since_id` dan pagination.
- Kecepatan notifikasi RSS tergantung jadwal refresh penyedia feed, bukan hanya
  interval bot. Pastikan feed mencakup balasan dan teks lengkap. Feed kosong,
  terpotong, atau tidak diperbarui bisa menyebabkan info terlewat. `--check-feed`
  menampilkan jumlah item yang dikenali; ini tidak membuktikan kelengkapan feed.
- Simpan cursor setelah postingan berhasil diproses; kiriman gagal dicoba lagi.
- Deteksi berbasis kata Codex + reset/refresh/replenish + limit/quota/usage/credit,
  atau pengumuman harian Tibo dengan pola Day N/ dan kata reset.
  Ini kandidat info, bukan konfirmasi bahwa limit akun pengguna sudah reset.
  Postingan di luar pola ini, konteks thread, gambar, dan variasi bahasa bisa luput;
  klaim masa depan atau pertanyaan bisa memicu notifikasi.
- SQLite mencegah duplikat normal dan setelah restart. Crash setelah Fonnte menerima
  pesan tetapi sebelum commit SQLite, atau timeout respons Fonnte, bisa menghasilkan
  duplikat saat retry. Tidak menjanjikan exactly-once delivery.
- Respons Fonnte hanya membuktikan pesan diterima API, bukan terkirim ke handset.
- Jika state hilang, postingan lama bisa diberitahukan lagi. Jika downtime melebihi
  jangkauan timeline X, beberapa postingan bisa terlewat.

## Validasi saat implementasi

14 unit test dan demo offline lulus. Akses live X dan pengiriman WA belum
terverifikasi karena URL feed dan kredensial belum tersedia.

## Batas X API

X API memiliki rate limit per endpoint/jendela waktu serta batas pemakaian atau
billing sesuai akses akun. Angka terbaru perlu dicek di developer console dan
https://docs.x.com/x-api/fundamentals/rate-limits; dokumentasi live tidak dapat
diakses dari environment ini saat perubahan Fonnte (HTTP 403).

Interval 300 detik berarti sekitar 288 poll per hari atau 8.640 per 30 hari
jika benar-benar berjalan terus, belum termasuk lookup user saat startup dan
request tambahan untuk pagination. Ini jumlah request, bukan jumlah postingan
atau biaya. `since_id` mengurangi pengambilan ulang postingan. HTTP 429 berarti
rate limit; bot mencoba lagi pada interval berikutnya. Kuota/billing habis tetap
memerlukan tindakan di developer console. Perbesar `POLL_SECONDS` untuk
mengurangi frekuensi request.

## Experiment: direct X scraper (read-only)

Branch `experiment/direct-x-scraper` adds a separate `scrape_x.py` command.
It does not import the WhatsApp sender, send messages, read Fonnte credentials,
or modify the RSS bot database. Existing RSS bot code is unchanged.

```sh
python -m unittest -q
python scrape_x.py
```

Uses installed Playwright Python and `/usr/bin/chromium`, inherited HTTPS proxy,
and normal TLS verification. Reads only articles rendered on the public profile;
no login automation, CAPTCHA bypass, private API, or RSS.app fallback. Output is
JSON on stdout. It fails explicitly if no recognizable posts are rendered.
It does not paginate, run a polling loop, or prove complete/reply coverage.

17 local tests passed, including author filtering, sorting and deduplication.
Live validation is blocked by the environment proxy denying x.com (CONNECT 403).
The x.com domain addition is saved in the environment draft; applying it does
not guarantee X will serve a public timeline. A login wall or JS resource
restrictions may remain. This is an experiment, not a verified RSS replacement.

## LLM judge prototype (not activated)

`scrape_x.py --judge` passes each complete extracted text to an OpenAI-compatible
API, with no keyword prefilter. Output is reset/not_reset/uncertain with a reason
and exact evidence. Responses are schema-validated and cached by model, prompt,
post ID and full text; invalid/incomplete responses are errors, never negatives.
This read-only prototype cannot send WhatsApp and is not connected to the live bot.
Requires JUDGE_API_KEY, JUDGE_MODEL and optionally JUDGE_BASE_URL; no requirements
or paid API configuration have been activated. User prefers their ChatGPT
subscription: it cannot be used as a Python API credential. An assistant-run
review is possible while a task is running, not an unattended 5-minute loop from
this chat. Existing live RSS bot still uses its previous keyword detection.
20 local tests pass; mocked API tests validate plumbing only, not LLM accuracy.
Full extracted text does not guarantee full original text when X renders a
truncated post; thread/quote context and media are not fetched by this prototype.

### Gemini free-tier guardrails (experiment only)

Default provider is now Gemini native generateContent API. Reuses the existing
`gemini_api_key` variable (also accepts GEMINI_API_KEY); never prints its value.
Default JUDGE_MODEL=gemini-2.5-flash; availability and actual free quota remain
unverified. Requires generativelanguage.googleapis.com allowed in network settings.

- Cache by full text/model/prompt: repeated posts do not consume API requests.
- Default 20 attempted calls per UTC day, persisted in the experiment cache DB;
  default 5 attempted calls per run. Failures count too; no automatic retries.
- Calls at least 15 seconds apart in a single process (not a global rate limiter).
- Maximum 4000 input characters per post; larger posts fail, never silently truncate.
- Gemini output capped at 256 tokens, thinking budget 0 for the default model.
- 429 stops the run. Caps stop the run before sending a further request.
- These are local safety budgets, NOT a guarantee against provider quota exhaustion.
  Other applications, multiple cache files, changed free-tier limits and token-based
  quotas can exhaust the real quota sooner. Preserve .local/judge-experiment.sqlite3.
- Initial live validation must use JUDGE_RUN_MAX_CALLS=1; don't judge all history.

23 local tests pass. No Fonnte call is performed by scrape_x.py --judge.
Current runtime still lacks gemini_api_key despite its saved configuration entry;
X and Gemini live requests currently fail at the proxy with CONNECT 403.
No Gemini live request has succeeded, and no main merge has been performed.

### Current experimental schedule and model

Use Gemini 2.5 Flash-Lite (`JUDGE_MODEL=gemini-2.5-flash-lite`), selected as the
budget text model among options in the user's free-tier screenshot. Screenshot
shows 10 RPM, 250K TPM and 20 RPD for this model; not proof of future quota.
Local default cap is 15 attempted requests per Pacific calendar day (rather than
UTC), leaving 5 requests of nominal margin. Other clients share project quota.

`python monitor_judge.py` runs one read-only cycle; `python monitor_judge.py --loop`
polls X every 600 seconds, independent of the existing RSS bot's 300-second loop.
No Fonnte sender is imported or called. First run queues only the newest visible
post, then queues newer IDs and processes at most one pending post each cycle.
No new post means no Gemini call; failed judgments remain pending. State lives
in .local/monitor-judge.sqlite3 and the existing judge cache. Budget exhaustion
leaves work pending. Old/late posts below the cursor are outside this experiment's
coverage; full timeline/replies and long-form post expansion are not verified.
This schedule means 144 source polls/day, NOT 144 Gemini requests/day.
25 local tests passed. Actual startup currently blocked by missing runtime Gemini
key. The experimental loop has not been launched and main has not been changed.

### Reset prefilter before Gemini

The experimental monitor now checks each queued post for the whole word `reset`
or `resets` (case insensitive). No mention means a recorded skip with zero LLM
calls. Mentions, including denials and jokes, pass the entire extracted text to
Gemini; only the LLM decides reset/not_reset/uncertain. The prefilter never declares
a reset. Posts using only synonyms, pictures, or other languages may be skipped.
The 600-second interval, 15-attempt daily cap and no-Fonnte mode remain unchanged.
27 local tests pass; judge accuracy and live scraper remain unverified.

### Verified Gemini model update

Default is now `gemini-3.5-flash-lite`. The API rejected 2.5 Flash-Lite for new
users and rejected the old thinkingBudget parameter for 3.5. That parameter is
removed; the 256-token output cap, cached verdicts and 15-attempt daily budget
remain. Thinking-token usage has not been separately verified for this model.
A live Gemini request classified the full Day 15 announcement as reset, citing
`and reset. Enjoy.`. No Fonnte call was made. This verifies one real verdict,
not general classification accuracy or the complete X scraping workflow.
Model setting saved to environment draft; review/save/publish is separate.
Chromium 154 uses ~/.local/share/pki/nssdb on this machine; the managed proxy CA
was imported there with certutil, preserving TLS verification.

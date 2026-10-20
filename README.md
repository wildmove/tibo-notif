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

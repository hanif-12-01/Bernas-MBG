# Vision AI dan pemeriksaan QC

Jalankan perintah dari direktori `services/api` dengan virtual environment proyek. Kunci provider dipasang pada proses API melalui pengelola rahasia atau environment privat. Jangan menyimpannya di repositori, memasangnya pada browser, atau memakai prefiks `NEXT_PUBLIC_`.

## Konfigurasi provider

| Variabel backend | Nilai |
| --- | --- |
| `GIZIOPTIMA_VISION_PROVIDER` | `openai` untuk provider yang dipilih Sprint 3A.5 |
| `OPENAI_API_KEY` | Kunci proyek yang diizinkan menjalankan analisis gambar |
| `GIZIOPTIMA_OPENAI_VISION_MODEL` | Opsional. Default `gpt-4o-mini`. Model pengganti harus menerima gambar dan JSON Schema Structured Outputs melalui Chat Completions. |
| `GIZIOPTIMA_ENV` | `production` pada deployment produksi. Mode uji Vision ditolak pada environment ini. |
| `GIZIOPTIMA_COOKIE_SECURE` | Aktifkan untuk cookie melalui HTTPS pada deployment. |

Adaptor Gemini tetap tersedia untuk konfigurasi eksplisit `GIZIOPTIMA_VISION_PROVIDER=gemini`, kunci privat `GEMINI_API_KEY` atau `GOOGLE_API_KEY`, serta `GIZIOPTIMA_GEMINI_MODEL` berisi ID model yang mendukung gambar dan keluaran JSON. Mode deterministik hanya berjalan jika secara eksplisit dipilih dengan `GIZIOPTIMA_VISION_PROVIDER=deterministic_test` di luar produksi. Nilai kosong atau salah menghasilkan status konfigurasi diperlukan dan HTTP 503 saat menganalisis.

Status Vision pada `GET /api/v1/health` menunjukkan konfigurasi yang dapat dibaca API. Untuk membuktikan koneksi live, gunakan akun Petugas QC, pilih rencana yang sudah disetujui, unggah foto makanan baru yang berizin, jalankan analisis, dan konfirmasi respons `provider_mode=live` dengan temuan tertaut ke foto. Catat keberhasilan, model, dan waktu respons. Analisis mengirim foto yang sudah dibersihkan ke provider untuk mengenali makanan yang terlihat. Perbandingan dengan rencana tersimpan dilakukan di backend aplikasi. Tinjauan petugas tetap diperlukan untuk mencatat koreksi visual.

Backend membatasi analisis ke 12 permintaan per menit per akun dalam satu proses. Koneksi yang gagal dan respons HTTP 502, 503, atau 504 dapat dicoba ulang sekali. Timeout sambungan 4 detik dan batas baca/tulis 14 detik per fase. Timeout baca, penolakan, respons tidak valid, kesalahan konfigurasi, dan HTTP 429 dikembalikan sebagai pesan yang dapat ditindaklanjuti tanpa meneruskan detail internal provider. Untuk deployment dengan beberapa worker atau replika, terapkan pembatasan terdistribusi di depan API.

## Foto privat dan retensi

JPEG, PNG, dan WebP statis dibatasi hingga 5 MiB per foto, 25 megapiksel, dan 12 foto per pemeriksaan. Penyimpanan lokal dapat ditetapkan melalui `GIZIOPTIMA_QC_STORAGE_DIR`. Simpan folder ini di luar root publik dan batasi akses filesystem ke operator layanan. Foto baru diputar sesuai orientasi EXIF, lalu dikodekan ulang dari piksel tanpa metadata sumber. API memeriksa keanggotaan dapur dan menolak akses foto setelah masa simpan.

`GIZIOPTIMA_QC_IMAGE_RETENTION_DAYS` menentukan masa simpan saat foto diunggah. Default 30 hari, dengan rentang 1–365 hari. Gunakan konfigurasi database dan direktori gambar yang sama dengan proses API. Jadwalkan perintah kedua pada lingkungan deployment untuk menghapus file kedaluwarsa. Metadata dan referensi riwayat pemeriksaan tetap tersimpan.

```powershell
.\.venv\Scripts\python.exe scripts/purge_expired_qc_images.py
.\.venv\Scripts\python.exe scripts/purge_expired_qc_images.py --apply
```

Saat melakukan backup, sinkronkan snapshot database dan direktori foto privat. Terapkan masa simpan yang sesuai pada backup dan pastikan pemulihan diuji sebelum mengandalkan backup.

## Evaluasi berlabel

Perintah tanpa `--live` memvalidasi foto dan label tanpa koneksi provider. Opsi `--live` mengirim foto yang sudah dibersihkan ke provider dan melaporkan matriks kebingungan, presisi, recall, F1 kehadiran komponen, tingkat keputusan pada label pasti, serta kasus yang gagal. Periksa jumlah kasus yang berhasil bersama metrik. Foto dengan label tidak pasti ikut dalam akurasi seluruh status dan dikeluarkan dari presisi/recall biner.

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_vision.py ../../qa/vision-held-out/manifest.json
.\.venv\Scripts\python.exe scripts/evaluate_vision.py ../../qa/vision-held-out/manifest.json --live
```

Foto harus berada di dalam direktori manifest. Set pilot mengukur visibilitas kategori pada data uji publik. Untuk menilai kinerja di dapur, gunakan foto berizin dengan kondisi cahaya, sudut, komponen, dan hidangan lokal yang beragam, serta label independen dari petugas. Penilaian visual tidak menetapkan kandungan gizi, gramasi, suhu, atau keamanan pangan.

[Model GPT-4o mini](https://developers.openai.com/api/docs/models/gpt-4o-mini) · [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) · [Input gambar](https://developers.openai.com/api/docs/guides/images-vision)

# Sprint 3A.5 — GiziOptima

## Rekomendasi rilis

**CONDITIONAL GO untuk demo dan uji internal.** Penggunaan operasional dengan Vision AI live masih menunggu kredensial backend, analisis satu foto baru yang berhasil, dan evaluasi foto menu yang mewakili kondisi dapur. Pengujian kamera pada perangkat fisik dan kesiapan deployment juga masih terbuka.

## Perubahan yang dapat dicoba

- **Perencana Menu** mengimpor dan memilih versi dataset, mengisi parameter rencana, menjalankan MILP, meninjau hasil, dan mengajukan rencana. Permintaan revisi tampil dengan catatan dan pengajuan ulang menghasilkan versi baru.
- **Kepala Dapur** meninjau rencana dan inspeksi tertunda, mencatat persetujuan/revisi/foto ulang, dan membaca jejak audit.
- **Petugas QC** memilih rencana yang disetujui, mengunggah melalui kamera atau galeri, memeriksa observasi untuk foto terbaru, mencatat koreksi, dan mengirim hasil. Permintaan foto ulang membuka tindak lanjut yang ditautkan ke laporan sebelumnya.
- **Operator server** membuat dapur dan akun, mengatur keanggotaan/peran, mereset sandi, dan menonaktifkan akses melalui [CLI backend](../services/api/README.md#pengelolaan-pengguna-dan-dapur). Perubahan sensitif dicatat dan sesi terkait dicabut.
- Dataset impor dibatasi per dapur dan demo sintetis bersama tetap berlabel. Cookie produksi memakai `Secure`. Upload, eksposur gambar, timeout, dan percobaan login/analisis dibatasi.

## Hasil tes

| Pemeriksaan | Bukti |
|---|---|
| Backend | **62 lulus** dalam 73,67 detik. Suite mencakup optimizer, migrasi, administrasi akses, RBAC, CSRF, lintas dapur, QC, provider gagal, foto kedaluwarsa, dan restart proses. Satu peringatan deprekasi Starlette TestClient. |
| Frontend | **13 lulus** di tiga file Vitest. TypeScript lulus. |
| Build produksi | **13 halaman statis** dibangun dengan Next.js 15.5.29. [Log build](evidence/production-build.log) |
| Impor sampai optimizer | CSV melalui browser; run `OPTIMAL`, `validation_passed=true`, dan ID versi dataset cocok. [Rencana dataset impor](evidence/desktop-rencana-impor.png) |
| Tinjauan rencana | Perencana mengajukan, kepala dapur meminta revisi, perencana mengajukan versi 2, kepala dapur menyetujui. [Ringkasan Kepala Dapur](evidence/desktop-kepala-dapur.png) |
| Vision tidak tersedia | Upload tetap bisa dilakukan. UI menampilkan konfigurasi diperlukan, analisis dinonaktifkan, dan API memberi 503. [Tampilan QC seluler](evidence/mobile-390-vision-konfigurasi.png) |
| QC dan tindak lanjut | Playwright memutus satu permintaan analisis, memeriksa pesan koneksi, lalu mencoba ulang. Analisis memakai provider uji berlabel non-live. Koreksi, kirim, keputusan foto ulang, dan pembuatan tindak lanjut berhasil. [Perbandingan QC 390 px](evidence/mobile-390-qc-perbandingan-uji.png) · [Log Playwright](evidence/browser-workflow.log) |
| Restart proses | Backend sungguhan direstart. Sesi, versi dataset, riwayat revisi, foto privat, koreksi dan keputusan QC, serta tautan audit tindak lanjut tetap dapat dibaca. [Log restart](evidence/browser-persistence.log) |
| Mobile dan desktop | Chromium Playwright lulus 105 kombinasi peran, rute, dan lebar 320, 375, 390, 428, 768, 1024, dan 1440 px tanpa overflow horizontal atau galat runtime. Drawer QC dan atribut kamera diuji. Kamera OS dan perangkat fisik belum diuji. [Matriks viewport](evidence/responsive-results.json) · [QC 320 px](evidence/mobile-320-qc-riwayat.png) |
| Akun dan dapur baru | Tes CLI mencakup pembuatan, perubahan peran, reset sandi, pencabutan sesi, dan penonaktifan. |
| Isolasi data | Browser dan backend menolak akses silang terhadap dataset, run, dan foto serta menolak perencanaan menggunakan dataset dapur lain. |
| Vision live | **Terblokir.** `OPENAI_API_KEY` tidak tersedia pada backend yang diuji. Tidak ada foto yang dikirim ke provider. [Status runner live](evidence/vision-live-status.json) |
| Evaluasi foto | **13 foto** split uji FoodSeg103, **52 label** slot dengan 30 terlihat, 19 tidak terlihat dan 3 tidak pasti. Manifest lulus. Belum ada metrik model. [Manifest](vision-held-out/manifest.json) · [Hasil validasi](evidence/vision-manifest-check.json) |

### Catatan deployment dan data

- Ikuti [konfigurasi Vision QC](../services/api/VISION_QC.md) untuk provider OpenAI, timeout, upload, evaluasi live dan retensi. Jadwalkan pembersihan foto sesuai masa simpan. Rate limiting berjalan per proses dan perlu koordinasi di proxy untuk banyak worker.
- Produksi memerlukan HTTPS, injeksi secret dari hosting, backup SQLite dan volume foto, serta uji pemulihan. Pengujian browser di loopback memverifikasi aplikasi pada lingkungan lokal.
- Peninjauan manusia wajib dalam alur QC. Analisis visual hanya mencatat komponen yang tampak. Data demo gizi tetap sintetis dan tidak memberi bukti kepatuhan atau integrasi BGN/SIPGN.
- Audit regresi awal memicu migrasi startup database demo lokal melalui introspeksi fixture lama. Fixture kini tidak membuka database selama koleksi. Database lokal lulus `quick_check` dan `foreign_key_check` di migrasi 0003. Pengujian Playwright memakai database sementara terpisah.
- FoodSeg103 adalah pilot publik dengan mask anotasi manual. Sampel tidak mewakili variasi kamera, pencahayaan dan menu Indonesia yang dibutuhkan untuk evaluasi operasional. [Sumber riset](https://github.com/LARC-CMU-SMU/FoodSeg103-Benchmark-v1)

## Inventaris perubahan

### Frontend `apps/web/src`

- `app/dashboard/page.tsx`, `app/globals.css`, `app/inventory/page.tsx`, `app/kitchen-qc/page.tsx`, `app/layout.tsx`, `app/login/page.tsx`, `app/menu-planning/page.tsx`, `app/settings/page.tsx`, `app/shopping-list/page.tsx`, `app/simulator/page.tsx`
- `app/fonts/plus-jakarta-sans-latin.woff2` dan `app/fonts/OFL.txt`. Font yang sama di-host lokal untuk menghilangkan ketergantungan build pada pengambilan Google Fonts.
- `components/dashboard/ManagerDashboardView.tsx`, `components/dashboard/QCOfficerDashboardView.tsx`, `components/layout/AppShell.tsx`, `components/menu/MenuReviewActionBar.tsx`, `components/menu/ScenarioPlanningForm.tsx`
- `hooks/useAuth.tsx`, `hooks/useWorkspace.tsx`, `lib/api/client.ts`, `types/api.ts`

### Backend `services/api`

- `app/main.py`, `app/api/upload_limit.py`, `app/api/routes/auth.py`, `app/api/routes/dashboards.py`, `app/api/routes/datasets.py`, `app/api/routes/qc.py`, `app/api/routes/scenarios.py`
- `app/auth/rate_limit.py`, `app/db/models.py`, `app/db/repository.py`, `app/db/session.py`, `app/ingestion/csv_parser.py`, `app/reviews/service.py`
- `app/vision/comparator.py`, `app/vision/image_security.py`, `app/vision/provider.py`, `app/vision/schemas.py`, `app/vision/service.py`, `alembic/versions/0003_dataset_kitchen_scope.py`
- `scripts/evaluate_vision.py`, `scripts/manage_access.py`, `scripts/purge_expired_qc_images.py`, `scripts/seed_demo_users.py`, `README.md`, `VISION_QC.md`
- `tests/test_audit_and_mutations.py`, `tests/test_optimizer_and_api.py`, `tests/test_sprint2a_persistence_and_api.py`, `tests/test_sprint3a5_access.py`, `tests/test_sprint3a5_vision.py`

### Bukti dan Obsidian

- `qa/run_sprint3a5.py`, `qa/sprint3a5.cjs`, `qa/README.md`, laporan ini, direktori `qa/evidence`, dan `qa/vision-held-out` dengan manifest, foto, dan mask bernomor ID asli.
- Obsidian `00_HOME`, PRD, User Flows, Multi-Actor Workflow and Permissions, Architecture, Database Schema, API Contract, Frontend UI UX Design System, Roadmap and Backlog, Sprint 3A.5 Validation Report, ADR-008, dan catatan harian 20 November 2026.

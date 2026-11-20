# Verifikasi Sprint 3A.5

Jalankan dari akar workspace dengan Python virtual environment backend, dependensi frontend terpasang, dan Chromium Playwright tersedia.

```powershell
.\services\api\.venv\Scripts\python.exe qa/run_sprint3a5.py --playwright-module 'C:\path\to\node_modules\playwright'
```

Runner membuat build Next.js, database SQLite, gambar uji, dan akun sementara. Server hanya mendengarkan di loopback. Jalur konfigurasi kosong diuji terlebih dahulu. Backend kemudian direstart dengan provider deterministik eksplisit untuk menguji alur persetujuan QC tanpa mengirim foto apa pun ke provider. Restart terakhir memeriksa persistensi dan membuka halaman ketiga peran di tujuh ukuran viewport. Ringkasan viewport, log, dan screenshot tersimpan di `qa/evidence`.

## Data evaluasi Vision

`vision-held-out/manifest.json` mengindeks 13 foto beserta mask anotasi manual dari split uji FoodSeg103. Label slot berasal dari kategori mask dan peninjauan foto. Contoh mencakup komponen terlihat, komponen yang tidak terlihat, objek yang sulit ditempatkan ke slot, dan piring dengan beberapa komponen. Buah yang dipakai sebagai garnish tetap diberi label terlihat untuk evaluasi pengenalan kategori.

- Sumber primer — [FoodSeg103 benchmark dan lisensi proyek](https://github.com/LARC-CMU-SMU/FoodSeg103-Benchmark-v1), Wu et al., *A Large-Scale Benchmark for Food Image Segmentation*, ACM Multimedia 2021.
- Salinan foto dan mask — [FoodSeg103 di Hugging Face](https://huggingface.co/datasets/justinsiow/FoodSeg103). ID asli dan checksum foto tersedia di manifest.
- Sampel ditetapkan untuk evaluasi dan tidak dipakai untuk menyesuaikan prompt. Sampel kecil dan berasal dari konteks foto publik. Metrik dari sampel ini belum cukup untuk menyimpulkan performa pada menu SPPG, makanan tertutup, pencahayaan dapur, atau hidangan Indonesia.

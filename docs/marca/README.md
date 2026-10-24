# Marca

`platia-icono-app.png` es el logo comercial original (1024 × 1024). El frontal usa copias
reducidas en `frontend/src/assets/`:

- `logo.png` (128 px): barra lateral, inicio de sesión y acceso denegado (`BrandMark`).
- `favicon.png` (64 px) y `apple-touch-icon.png` (180 px): icono de la pestaña y del móvil.

Para cambiar el logo, sustituye el original y regenera las copias, por ejemplo con ImageMagick:

```
convert docs/marca/platia-icono-app.png -resize 128x128 -strip frontend/src/assets/logo.png
convert docs/marca/platia-icono-app.png -resize 64x64 -strip frontend/src/assets/favicon.png
convert docs/marca/platia-icono-app.png -resize 180x180 -strip frontend/src/assets/apple-touch-icon.png
```

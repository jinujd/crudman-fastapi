---
title: File uploads
---

# File uploads

## Shorthand

```python
crud_router(Profile, config={
    "uploadable": {"avatar": "image-avatar"},
    "upload_defaults": {"storage": "local"},
})

CrudmanOptions(
    default_file_storage="local",
    file_storages={"local": LocalStorage(dest="uploads", public_base_url="http://localhost:8000/uploads")},
)
```

Clients can send:

- multipart: field `avatar` as a file
- JSON base64: `{"avatar": "data:image/png;base64,iVBORw0..."}`

A plain string that is not a data URL (for example the existing filename sent back on update) is left as
is. On create, a single file field is required.

Shorthand suffixes:

| Spec | Meaning |
| --- | --- |
| `"image"` | one file, stored by filename (default) |
| `"image-jpg[]"` | several files |
| `"image:base64"` | keep base64 text in `avatarBase64` |
| `"binary:blob"` | store bytes in `rawBlob` plus mime in `rawMime` |

## Full control

```python
Section(upload={"map": [
    UploadMap(
        source_field="file",
        storage_mode="filename",              # filename | filename_in_field | base64 | blob
        storage="s3",
        target_field={"key": "file_key", "url": "file_url"},
        type_hint="pdf",
        validators={"max_size_mb": 10, "allowed_extensions": [".pdf"]},
    ),
]})
```

## Presets

| Preset | Types | Max MB |
| --- | --- | --- |
| `image` | jpeg, png, gif, webp, avif | 5 |
| `image-jpg`, `image-png`, `image-gif`, `image-webp`, `image-avif` | one type each | 5 |
| `image-avatar` (and `-jpg`, `-png`, `-webp`, `-avif` variants) | images, 128 to 4096 px, about 1:1 | 2 |
| `video`, `video-mp4`, `video-webm`, `video-ogg` | video | 100 |
| `video-short` | mp4, webm | 25 |
| `audio` | mp3, m4a, aac, ogg, wav | 20 |
| `pdf` | .pdf | 10 |
| `doc` | .pdf, .doc, .docx, .odt | 10 |
| `spreadsheet`, `spreadsheet-csv`, `spreadsheet-xls`, `spreadsheet-xlsx` | spreadsheets | 5 to 10 |
| `text`, `csv`, `xml`, `html`, `json` | text formats | 2 to 5 |
| `archive` | zip, tar, gz, rar, 7z | 200 |
| `binary` | octet-stream | 50 |
| `any` | no restriction | |

Validator precedence: preset, then global `upload_limits`, then section `upload_defaults.validators`, then
the rule's own `validators`.

Error types: `required`, `fileSize`, `fileExtension`, `fileMime`, `imageDimensions`, `imageAspect`.

## Response

```json
{
  "data": [ { "id": 1, "avatar": "uploads/3f2c.png" } ],
  "meta": { "baseUrls": { "avatar": "http://localhost:8000/uploads/" } }
}
```

`upload_response={"file_field_mode": "key_url_fields"}` writes `avatarKey` and `avatarUrl` instead of
`avatar`. Send `x-file-url: full` or `key_only` to have the preference echoed in `meta.fileUrlMode`.

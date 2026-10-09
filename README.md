# doc-markdown

Convert one local file to Markdown inside Hermes Agent with `doc_convert`, built on Microsoft's MarkItDown (MIT).

Microsoft and MarkItDown are trademarks of the Microsoft group of companies. The name decision follows Microsoft's [general trademark guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general.aspx). This repository does not ship a Microsoft logo. The product name does not contain MarkItDown. Upstream copyright is `Copyright (c) Microsoft Corporation.` in [their LICENSE](https://github.com/microsoft/markitdown/blob/main/LICENSE).

> **日本語の要約**は末尾です。英語の節が先です。

## Install

```bash
hermes plugins install doc-markdown --enable
# or, from a clone of this repo:
hermes plugins install "file://$PWD" --enable
```

Needs Hermes v0.21.4 or later (`requires_hermes: >=0.21.4`, `manifest_version: 2`, plugin version 0.1.0). The dependency is declared in `plugin.yaml`:

`markitdown[pdf,docx,pptx,xlsx,xls]>=0.1.0,<0.2`

The floor is 0.1.0 because this plugin imports `markitdown.converters` and `StreamInfo(charset=)`. PdfConverter, DocxConverter, XlsxConverter, XlsConverter, PptxConverter, HtmlConverter, and PlainTextConverter also exist in markitdown 0.0.2 as one module. CsvConverter does not. Local files call one converter class and do not use `convert_local`. The `markitdown.converters` imports and `StreamInfo(charset=)` were not executed on 0.1.0. The installed package at the last recheck was 0.1.8. Extras included: `pdf`, `docx`, `pptx`, `xlsx`, `xls`. HTML, CSV, and TXT use MarkItDown core. Not installed by default: `youtube-transcription`, `audio-transcription`, `az-doc-intel`, `az-content-understanding`.

If `markitdown` cannot be imported, the tool returns `dependency_missing`. The next step is `hermes plugins validate <plugin-dir> --install-deps`.

v0.1 converts local files only. It does not register a web extract provider.

> **Warning:** `doc_convert` can read any absolute allowlisted path the Hermes process can open (for example `~/secrets.json`). It is not a chroot or a user-home sandbox. The conversion worker is not a sandbox for a hostile file.

## What it registers

| Surface | Name | Role |
|---|---|---|
| Tool | `doc_convert` | One absolute local path to Markdown |
| Toolset | `doc_markdown` | On by default on every surface, including gateway. Stop it with `hermes tools`. |

There is no slash command, no CLI, no cron, no hook, and no web provider. `requires_env` is empty. The plugin reads no other tool's credentials. It writes no files under `<HERMES_HOME>/plugin-data/doc-markdown`.

The toolset is on for every surface, including gateway, as soon as the plugin is enabled. Anyone you allow onto a gateway can call `doc_convert` on an allowlisted path the process can open. Stop the toolset per surface with `hermes tools`. The name to disable is `doc_markdown` (underscore).

The agent can call `doc_convert` itself. There is no daily call cap. This plugin creates no cron job. An unattended session still converts if Hermes calls the tool. The cost is the calling turn. Paid MarkItDown extras (`az-doc-intel`, `az-content-understanding`) are not in the default dependency.

Platforms are Linux and macOS. Windows was not tested. The worker uses Unix process control, so Windows is not in `platforms`.

## Local tool

`doc_convert` reads one absolute path. It resolves with `realpath`, then judges the result.

- Refused: the Hermes home, any path component that starts with `.` (for example `.secrets` or `.git`), a relative path, `http`, `https`, or `file` URLs in any letter case, a missing file, a directory, an extension outside the allowlist, and a file over `max_file_bytes` (default 20971520). A missing path or a directory inside the Hermes home is `path_not_allowed`, not `file_not_found` or `not_a_file`.
- The Hermes home is only `hermes_constants.get_hermes_home`. A path string or a path object is accepted. Import failure, an exception, a missing or renamed function, or a return that is not a path is `path_not_allowed` and does not fall back to `HERMES_HOME` or `~/.hermes`.
- A `.zip` extension is `unsupported_type` before conversion. A file whose bytes are a zip, including a zip renamed to another extension, is `zip_refused` before any converter runs. A non-Office allowlisted file is treated as a zip only when it begins with a full signature: `PK\x03\x04` (local header), `PK\x05\x06` (end of central directory), or `PK\x07\x08` (spanned). The two bytes `PK` are not enough, so a CSV that starts with `PK,Name,Email` and a Markdown file that starts with `PKI rollout` are converted as text.
- `.docx`, `.xlsx`, and `.pptx` continue only when the package contains `word/document.xml`, `xl/workbook.xml`, or `ppt/presentation.xml`. That file is passed only to that format's converter. A chart in a `.pptx` can store an `.xlsx` inside the package; that presentation still converts. A zip that lacks the package part is `zip_refused`. Nested zip depth is not measured, and the archive converter is not used.
- For a `.docx`, `.pptx`, or `.xlsx` that has that package part, the plugin sums, for each member, the larger of the outer central-directory `ZipInfo.file_size` and the local-header uncompressed size when that header stores one (general-purpose bit 3 clear). It does not extract members. Over `max_file_bytes` is `uncompressed_too_large`. If those two sizes disagree and the larger sum is still within the cap, the file is `zip_refused`. When bit 3 is set, only the central-directory size is known without reading the compressed bytes, and the reader does not emit more uncompressed bytes than that declared size. A declared size can still understate a deflate stream. The memory limit below is what stops that expansion.
- A `.docx`, `.pptx`, or `.xlsx` that is not a readable zip is `conversion_failed`. A `.xls` whose bytes are a zip is `zip_refused`. A `.xls` that is not a zip stays best-effort.
- Local `.html` and `.htm` use a meta charset in about the first 8 KiB. Shift_JIS-family labels (`shift_jis`, `shift-jis`, `sjis`, `x-sjis`, `windows-31j`, `ms_kanji`, `ms932`, `csShiftJIS`, `cp932`) are read as cp932. Any other declared charset that Python knows is used as declared. A declared name Python does not know is `encoding_unconfirmed`, not a UTF-8 success. With no meta tag the file must be UTF-8. The bytes are decoded and re-encoded as UTF-8 before MarkItDown sees them. Only a meta tag's charset attribute is rewritten to utf-8. Other text, including the letters `charset=`, is left as decoded. Local `.txt`, `.md`, `.csv`, and `.json` are UTF-8 only. Bytes that are not valid in that charset are `encoding_unconfirmed`, not a successful conversion. This plugin does not guess a local text encoding.
- Local conversion runs in one worker process. The worker loads its converters first. `convert_timeout_seconds` defaults to 8. That value is the wall clock for the conversion after loading. When it is reached, the plugin stops the worker process group and returns `conversion_timeout` with an English sentence that names the time limit. A worker that does not finish loading is stopped at 60 seconds, with a different English sentence. The same worker is stopped at 922746880 bytes of memory (880 MiB). On Linux the worker sets `RLIMIT_AS` to that value before converting. On macOS the parent watches the worker's RSS and stops the process group when RSS exceeds it. If that watch cannot read `ps`, including an exit of 0 with no RSS number, the tool returns `memory_watch_failed` and does not return success. When the limit is exceeded the tool returns `conversion_memory` and does not return success. The memory limit is not a config key and `max_file_bytes` does not raise it. The worker is not a sandbox for a hostile file. The child process does not receive Hermes environment variables or API keys. It receives only PATH, HOME, USER, LOGNAME, LANG, LC_ALL, LC_CTYPE, LC_NUMERIC, TZ, TMPDIR, TMP, and TEMP when those are set, plus PYTHONUTF8, PYTHONIOENCODING, and PYTHONSAFEPATH when set, and it always sets PYTHONUNBUFFERED=1. PYTHONPATH is also passed through when set, because Hermes 0.21.6 and later hand dependency paths to child processes through it.
- If the worker cannot load this plugin at all, the error says which kind of failure it was: a missing third-party package is `dependency_missing` (`markitdown is not installed in this Hermes environment.` when markitdown itself is the missing one), while an unreadable, incomplete, or uncompilable plugin directory is `plugin_load_failed`. The exception class name is in `reason`.
- On success, `truncated`, `char_count`, and `error` are placed before `markdown` (`error` is null), so a 1500-character preview still shows whether the text was cut. `max_chars` above `max_output_chars` (default 200000) is not an error; the cut stays at the config. `0`, a negative value, or a non-integer is `bad_argument`.
- Handlers do not raise. Failures are JSON `error`, `error_type`, and `next_step`. Empty conversion, including text that is only a form feed, is `empty_output`. An unexpected exception is `internal`. Failure logs are the basename and the exception type, not the file bytes.

There is no daily call cap. The agent can call the tool itself. This plugin creates no cron job. An unattended session still converts when Hermes calls the tool. The conversion worker is not a sandbox for a hostile file. Removing the plugin deletes its directory and install metadata. It does not uninstall the markitdown package. On Hermes 0.21.4, `plugins.enabled` can still list `doc-markdown`. On current main, remove also clears `plugins.enabled`, `plugins.disabled`, and `plugins.entries`, and turns the toolset off. This plugin creates no cron, so none remains. It reads one unpublished Hermes part, `hermes_constants.get_hermes_home`. A Hermes update that changes that part can stop the plugin, and a failure there refuses the read. The `tests/` directory is shipped in the repository and is not loaded by `register()`.

Every MarkItDown call starts one worker process, loads the converters, and then stops that process group at `convert_timeout_seconds` (defaults to 8) or at 922746880 bytes. Loading is stopped at 60 seconds. It does not start a shell. The converters this plugin calls do not start exiftool. Image and audio conversion, which can start exiftool, are not used. Running with exiftool installed was not tested.

Large but valid files (for example an 800-page PDF or a 30,000-row spreadsheet) can reach the 8-second clock and return `conversion_timeout`. Raise `convert_timeout_seconds` in the plugin config if you need them.

Not tested here:

- Password-protected Office internals and a real `.xls` success.
- Windows.
- A live gateway session.
- Whether the Microsoft trademark-list PDF contains the word MarkItDown (the name follows the general guidelines).
- An approval UI (this plugin has no approval feature).

Conversion quality is MarkItDown's result for that file. A scanned PDF with no text layer may be short text or `empty_output`. A password-protected Office file may be `conversion_failed`. Re-check fixture wording with `pytest -q` on `tests/fixtures/`. The checked fixture words are "Sample Report" (pdf, docx, pptx, html), "widget" (xlsx), and "gadget" (csv).

## Develop / test

Dependencies come from `plugin.yaml` (`hermes plugins validate . --install-deps`). Then:

```bash
pytest -q
```

```bash
hermes plugins validate . --install-deps
```

## 日本語

**doc-markdown** は、手元のファイルを Markdown にする道具 `doc_convert` です。v0.1 は web 抽出の提供元を登録しません。Microsoft の MarkItDown（MIT）の上に構築しています。Microsoft と MarkItDown は Microsoft の商標です。

1. `hermes plugins install doc-markdown --enable`（このリポジトリなら `hermes plugins install "file://$PWD" --enable`）
2. ツールセット名は `doc_markdown`。既定ですべての面（ゲートウェイを含む）で有効です。止めるのは `hermes tools` です。

日ごとの呼び出し上限は無く、このプラグインは cron を作りません。エージェント自身が道具を呼べます。無人のセッションでも、Hermes が道具を呼べば変換します。保存先の plugin-data はありません。削除はディレクトリと導入メタデータを消し、markitdown のパッケージは消しません。Hermes 0.21.4 では `plugins.enabled` に `doc-markdown` が残ることがあります。今の main は `plugins.enabled` と `plugins.disabled` と `plugins.entries` も消し、ツールセットを切ります。cron は作らないので残りません。対応 OS は Linux と macOS です。Windows は試していません。

`doc_convert` はサンドボックスではありません。realpath のあと、許可拡張子の絶対パスでプロセスが開けるものは読めます（例: `~/secrets.json`）。拒否するのは Hermes ホーム、`.` で始まるパス成分の全部、相対パス、`http` / `https` / `file`、無いファイル、ディレクトリ、サイズと種別です。スキームは大小文字を無視して見るので、`HTTPS://example.com/a.pdf` や `FILE:///tmp/a.txt` も `url_not_allowed` です（`bad_path` ではありません）。`ftp://` など他のスキームは、絶対パスでないので `bad_path` のままです。OS の隠し属性では拒否しません。`CASE.TXT` は読めます。ホームの中にあるシンボリックリンクが外を指す場合は読めます。外にあるリンクがホームの中を指す場合は `path_not_allowed` です。ホームは `hermes_constants.get_hermes_home` の戻り値だけです。パスの文字列でもパスオブジェクトでも受けます。import の失敗、例外、関数の改名、パスでない戻り値では変換せず、`HERMES_HOME` や `~/.hermes` には戻りません。ホームの中の無いパスとディレクトリも `path_not_allowed` です。

`.xls` は best-effort で、成功の専用フィクスチャは無く、`conversion_failed` になり得ます。拡張子 `.zip` は変換の前に `unsupported_type` です。中身が zip のファイルは、変換器を呼ぶ前に `zip_refused` です。zip の判定は完全な署名（`PK\x03\x04`、`PK\x05\x06`、`PK\x07\x08`）です。先頭 2 バイトの `PK` だけでは拒否しません。`PK,Name,Email` で始まる CSV と `PKI rollout` で始まる Markdown は変換します。`.docx` `.xlsx` `.pptx` は、`word/document.xml`、`xl/workbook.xml`、`ppt/presentation.xml` があるときだけ、その形式の変換器に渡します。部品がある Office ファイルは、各部材について、中央ディレクトリの `file_size` と、ローカルヘッダがサイズを持つときの非圧縮サイズの大きい方を足し、合計が `max_file_bytes`（既定 20971520）を超えたら `uncompressed_too_large` です。二つが食い違い、大きい方が上限以内なら `zip_refused` です。申告サイズが実際の deflate より小さくても、ワーカーのメモリ上限で止めます。上限は 922746880 バイト（880 MiB）です。Linux はワーカーが `RLIMIT_AS` をこの値にし、macOS は親が RSS を見て超えたらプロセスグループを止めます。`ps` が読めないとき、終了コード 0 で RSS の数値が無いときも含めて、`memory_watch_failed` で止め、成功は返しません。上限を超えたときは `conversion_memory` で、成功は返しません。この上限は設定では上がりません。変換の時計は、変換器を読み込んだあと `convert_timeout_seconds` の既定は 8 秒です。読み込みが終わらないときは 60 秒で止めます。子プロセスには Hermes の環境変数と API キーを渡しません。このワーカーは敵対的なファイルの砂場ではありません。

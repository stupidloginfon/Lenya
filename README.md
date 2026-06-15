# Lenya — конвейер виральных коротких видео

Находит залетевшие ролики в TikTok / YouTube Shorts / Instagram Reels, разбирает
их хуки через Claude, генерирует похожие видео под твою тему, вставляет рекламу и
загружает результат на площадки.

```
discover → download → analyze → generate → advertise → upload
 (поиск)   (скачать)  (оценка    (новое      (реклама)   (выложить)
                      хука AI)   видео+TTS)
```

## Как это работает

| Стадия | Что делает | Чем |
|---|---|---|
| **discover** | собирает список трендовых роликов по запросам/хэштегам | `yt-dlp` |
| **download** | качает исходник + метрики (просмотры/лайки) | `yt-dlp` |
| **analyze** | транскрибирует первые 5 сек, оценивает «виральность» хука и достаёт переиспользуемый шаблон | `faster-whisper` + LLM |
| **generate** | пишет новый сценарий по шаблону хука, озвучивает, собирает вертикальное видео с субтитрами | LLM + TTS + `ffmpeg` |
| **advertise** | накладывает баннер с CTA и/или вклеивает рекламный ролик | `ffmpeg` |
| **upload** | публикует на YouTube (готово), TikTok/Instagram (заготовки) | YouTube Data API |

Состояние хранится в SQLite (`data/lenya.db`), так что один ролик не обрабатывается дважды.

## Что нужно для работы

1. **Python 3.10+**
2. **ffmpeg и ffprobe** (системные бинарники):
   - Ubuntu/Debian: `sudo apt install ffmpeg`
   - macOS: `brew install ffmpeg`
   - Windows: `winget install ffmpeg`
3. **Ключ LLM-провайдера** — бесплатно (Groq по умолчанию) или платно (Claude). См. ниже.
4. *(опц.)* **OAuth-файл Google** для загрузки на YouTube
5. *(опц.)* шрифт `.ttf` для баннера рекламы (обычно уже есть в системе)

## Установка

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env        # и впиши ANTHROPIC_API_KEY
```

> `faster-whisper` тяжёлый. Если не нужна транскрипция хука — можешь его не ставить,
> пайплайн отработает без текста хука (оценка пойдёт только по метрикам + заголовку).

### LLM-провайдер (бесплатно или на Claude)

Анализ хука и генерация сценария идут через единый адаптер (`pipeline/llm.py`).
Провайдер выбирается одной строкой `LLM_PROVIDER` в `.env`:

| Провайдер | Цена | Где взять ключ | Модель по умолчанию |
|---|---|---|---|
| `groq` *(дефолт)* | бесплатно, без карты | [console.groq.com](https://console.groq.com) → `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| `gemini` | бесплатный тариф | [aistudio.google.com](https://aistudio.google.com) → `GEMINI_API_KEY` | `gemini-2.0-flash` |
| `openrouter` | есть модели `:free` | [openrouter.ai](https://openrouter.ai) → `OPENROUTER_API_KEY` | `llama-3.3-70b-instruct:free` |
| `ollama` | бесплатно, офлайн | ключ не нужен, `ollama serve` | `qwen2.5` |
| `claude` | платно | [console.anthropic.com](https://console.anthropic.com) → `ANTHROPIC_API_KEY` | `claude-opus-4-8` |

Модель/URL можно переопределить через `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY`.
Для старта: получи бесплатный ключ Groq, впиши `GROQ_API_KEY=...` в `.env` — готово.

### Озвучка

Два варианта на выбор (`TTS_ENGINE` в `.env`):

- **edge** (по умолчанию) — нейроголоса Microsoft, звучат отлично, но нужна сеть.
- **piper** — офлайн-нейросеть, тоже звучит естественно, работает без интернета.
  Скачай модель голоса и укажи путь в `PIPER_MODEL`:
  ```bash
  mkdir -p assets/voices && cd assets/voices
  BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/dmitri/medium
  curl -fLO $BASE/ru_RU-dmitri-medium.onnx
  curl -fLO $BASE/ru_RU-dmitri-medium.onnx.json
  # затем в .env:  TTS_ENGINE=piper  PIPER_MODEL=./assets/voices/ru_RU-dmitri-medium.onnx
  ```

> `tools/demo.py` сам подхватит модель из `assets/voices/` или `PIPER_MODEL`, иначе
> откатится на espeak-ng (звучит роботизированно — только для проверки сборки).

## Использование

```bash
# 1. Найти ролики (запрос -> поиск по Shorts; либо вставь URL хэштега TikTok/Reels)
python main.py discover "как заработать деньги" "фитнес мотивация" --limit 15

# 2-3. Скачать и проанализировать всё найденное
python main.py download --all
python main.py analyze --all

# Посмотреть, что отобралось (status=analyzed — принятые хуки)
python main.py list

# 4. Сгенерировать новое видео под свою тему по хуку ролика №3
python main.py generate 3 --topic "мой курс по Python для новичков"

# 5. Вставить рекламу (берётся AD_TEXT / AD_CLIP из .env)
python main.py advertise 3

# 6. Загрузить
python main.py upload 3 --to youtube
```

Или всё разом:

```bash
python main.py run "тренды о деньгах" --topic "мой телеграм-канал" --to youtube
```

### Настройки (`.env`)

| Переменная | Зачем |
|---|---|
| `LLM_PROVIDER` | провайдер LLM: `groq` (дефолт) / `gemini` / `openrouter` / `ollama` / `claude` |
| `GROQ_API_KEY` и т.п. | ключ выбранного провайдера (для `claude` — `ANTHROPIC_API_KEY`) |
| `LLM_MODEL` | переопределить модель провайдера (необязательно) |
| `BROLL_DIR` | папка с твоими фоновыми клипами `.mp4` |
| `TTS_ENGINE` | движок озвучки: `edge` (нейроголоса Microsoft) или `piper` (офлайн) |
| `TTS_VOICE` | голос для edge (`edge-tts --list-voices`) |
| `PIPER_MODEL` | путь к `.onnx` модели для piper |
| `AD_TEXT` | текст баннера-рекламы |
| `AD_CLIP` | путь к рекламному ролику для вклейки в конец |
| `WHISPER_MODEL` | размер модели транскрипции (`tiny`…`large-v3`) |
| `HOOK_SCORE_THRESHOLD` | порог отбора виральных хуков (0–100) |

## Загрузка на площадки

- **YouTube** — работает «из коробки». Нужен OAuth-клиент (тип *Desktop app*) из
  Google Cloud Console с включённым **YouTube Data API v3**. Скачай `client_secret.json`,
  укажи путь в `YOUTUBE_CLIENT_SECRET`. При первой загрузке откроется браузер для входа,
  токен закэшируется в `youtube.token.json`.
- **TikTok** — заготовка (`pipeline/upload.py`). Требуется одобренный доступ к
  **Content Posting API** (scope `video.publish`) на developers.tiktok.com.
- **Instagram Reels** — заготовка. Требуется **Graph API**, бизнес-аккаунт и публичный
  URL файла (Instagram скачивает видео сам). Точки подключения расписаны в коде.

## Структура

```
config.py            — настройки из .env
main.py              — CLI
pipeline/
  discover.py        — поиск (yt-dlp)
  download.py        — скачивание (yt-dlp)
  analyze.py         — транскрипция + оценка хука (Claude)
  generate.py        — сценарий + озвучка + сборка видео
  advertise.py       — вставка рекламы (ffmpeg)
  upload.py          — выгрузка (YouTube + заготовки)
  ffmpeg_utils.py    — обёртки над ffmpeg/ffprobe
  db.py              — состояние пайплайна (SQLite)
data/                — скачанное, результаты, БД (в .gitignore)
```

## Важно: право и правила площадок

- **Авторские права.** Перезаливать чужие ролики нельзя. Инструмент задуман как
  анализатор приёмов: он берёт *шаблон хука* (структуру, а не контент) и генерирует
  **новое** видео на твоём материале. Для фона клади свои клипы в `BROLL_DIR` — если
  их нет, как фон подставляется обрезанный исходник, и ответственность за это на тебе.
- **Правила платформ.** У TikTok/YouTube/Instagram есть ограничения на автоматическую
  выгрузку и на повторяющийся/«спамный» контент. Используй официальные API, не
  заливай массово однотипное — аккаунты за это банят.
- **Маркировка рекламы.** Рекламные вставки маркируй по требованиям своей юрисдикции.

Используй на свой риск и только для контента, на который у тебя есть права.

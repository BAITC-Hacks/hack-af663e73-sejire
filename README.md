# Умный подбор подрядчиков

Авторы: **Alexey Azovskiy** и **Amir Meirmanov**.

## Открыть

| Куда | Ссылка |
| --- | --- |
| Сервис | [https://sports-flush-saves-condition.trycloudflare.com](https://sports-flush-saves-condition.trycloudflare.com) |
| Панель администратора | [https://sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin) |
| Репозиторий | [https://github.com/BAITC-Hacks/hack-af663e73-sejire](https://github.com/BAITC-Hacks/hack-af663e73-sejire) |

Публичный адрес — временный туннель Cloudflare. Страница открывается, пока работают сервис и туннель. Логин администратора: `admin`. Пароль первого входа: `Astana2026`. Его можно сменить в панели.

## 1. Название

Умный подбор подрядчиков.

## 2. Краткое описание

Сервис помогает организатору мероприятия быстро получить короткий список подрядчиков из каталога. Пользователь задаёт город, дату, длительность, формат, характер мероприятия и бюджет в тенге. В ответ приходит не больше трёх карточек: у каждой есть конкретное объяснение по полям каталога и открытый счёт. Рядом показано, почему другие записи не прошли условия.

Отдельный вход есть у администратора: он дополняет каталог по одной записи или файлом CSV.

## 3. Что реализовано

- Форма подбора: город, дата, длительность в часах, формат, характер мероприятия, бюджет, число гостей, язык мероприятия и услуги. Длительность можно не указывать.
- Жёсткий фильтр. В список попадает только тот, у кого совпали город, дата внутри окна доступности и вне периода занятости, формат, категория, бюджет внутри вилки, а если заданы — услуги, язык, вместимость и длительность не больше максимума часов.
- Сортировка по счёту: число сделанных работ плюс близость бюджета к середине вилки. Одинаковый запрос даёт один и тот же порядок.
- До трёх карточек. На карточке — название, объяснение, счёт вида «работы + близость = итог».
- Таблица сравнения и до трёх причин отказа. Причины берутся по разным типам: город, бюджет, дата и далее.
- Интерфейс и тексты объяснений на русском, казахском и английском. Значения в каталоге хранятся как есть, подписи к ним переводятся.
- Админ-панель: вход, смена пароля, добавление и правка подрядчика, даты занятости «с» и «по», максимум часов, загрузка CSV, удаление строки.
- Стартовый каталог из девяти подрядчиков в `data/contractors.csv`. Новые значения, которые администратор сохраняет, появляются в списках формы.

## 4. Как работает решение

1. При первом запуске `app.py` создаёт SQLite-базу `data/contractors.db`. Если она пустая, строки читаются из `data/contractors.csv`.
2. Браузер открывает `static/index.html` и запрашивает списки у `GET /api/options`.
3. Пользователь нажимает «Подобрать». Страница вызывает `GET /api/match` с выбранными полями.
4. Сервер оставляет только записи, которые проходят все заданные условия.
5. Оставшиеся сортируются по убыванию счёта, при равенстве — по названию. В ответ уходят первые три.
6. Для остальных собирается до трёх отказов, по одному на тип причины.
7. Страница показывает карточки, таблицу сравнения и список отказов.

Счёт считается так: `число работ + (1 − |бюджет − середина вилки| / ширина вилки)`. Близость лежит от 0 до 1 и на экране округляется до двух знаков.

## 5. Технологии

- Python 3, только стандартная библиотека: `http.server`, `sqlite3`, `csv`, `json`, `hashlib` (scrypt), `hmac`, `secrets`.
- Страницы — HTML, CSS и JavaScript без фреймворков и без сборки: `static/index.html`, `static/admin.html`.
- Подбор модель не вызывает: объяснение карточки — шаблон из полей каталога. В админке можно отдельно сохранить адрес API. Кнопка «Проверить отзывы» спрашивает этот API про конкретного подрядчика и не меняет список на главной. Без ключа подбор работает как раньше. Сервис сам не открывает 2GIS и Instagram.
- Публичный адрес отдаёт Cloudflare Tunnel. Приложение само в Cloudflare не обращается.

## 6. Архитектура

```text
браузер
  static/index.html  →  GET /api/options, GET /api/match
  static/admin.html  →  POST /api/admin/login, /password, /contractors, /import, /delete, /check
        │
        ▼
app.py  (ThreadingHTTPServer)
  search()   фильтр, счёт, три карточки, причины отказа
  sqlite3    data/contractors.db
  csv        data/contractors.csv   (начальное наполнение)
  json       data/admin.json        (хеш пароля, создаётся при первом запуске)
```

Сессия администратора хранится в памяти процесса: cookie `session`, HttpOnly, SameSite=Lax, 12 часов. Перезапуск сервера завершает сессию. База и файл пароля в git не входят.

Основные пути:

- `GET /` и `GET /admin` — страницы.
- `GET /api/options?lang=ru|kz|en` — списки для формы.
- `GET /api/match` — подбор.
- `POST /api/admin/login`, `/logout`, `/password`, `/contractors`, `/import`, `/delete`.

`Procfile` запускает сервис командой `python app.py`. Если задана переменная `PORT`, сервер слушает её. Без `PORT` порт 8080.

## 7. Установка и запуск

Нужен Python 3. Сторонние пакеты ставить не требуется.

В каталоге репозитория:

```powershell
python app.py
```

Откройте [сервис](https://sports-flush-saves-condition.trycloudflare.com).

Если команда `python` не находится, запустите установленный интерпретатор Python 3. При первом запуске в консоли будут логин `admin` и пароль `Astana2026`. После смены пароля в панели консоль пишет, что пароль изменён.

## 8. Как проверить решение

Форма уже заполнена примером: Астана, 2026-09-23, офлайн, конференция, 1 500 000 тг. Нажмите «Подобрать».

Ожидаемый порядок:

| Место | Подрядчик | Счёт |
| --- | --- | --- |
| 1 | Astana Events | 18 + 0.91 = 18.91 |
| 2 | Сарыарка Холл | 11 + 0.83 = 11.83 |
| 3 | Expo Crew | 7 + 1.00 = 8.00 |

В отказах: Алматы Ивент (другой город), «Свет до 500 тысяч» (бюджет вне вилки), «Сцена без окна» (дата вне окна).

Второй прогон: тот же город, дата, формат и бюджет, характер — «концерт». В каталоге эта категория есть только у Steppe Stage, поэтому в выдаче одна карточка.

Админ-панель: [https://sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin), логин `admin`, пароль `Astana2026`. В панели его можно сменить: текущий пароль, новый и повтор. Новый пароль — не короче 6 символов.

## 9. Данные и интеграции

Единственный источник подбора — каталог сервиса.

Файл `data/contractors.csv`, 9 строк. Колонки: `id`, `name`, `city`, `categories`, `formats`, `budget_min`, `budget_max`, `available_from`, `available_to`, `done_count`, `capacity`, `languages`, `services`, `busy_from`, `busy_to`, `max_hours`. Несколько значений в ячейке пишутся через `|`. Даты занятости и максимум часов в стартовом файле пустые.

При пустой базе файл загружается в `data/contractors.db`. Дальше подбор читает базу. CSV до 1 МБ, кодировка UTF-8. Если `id` уже есть, строка обновляется. Без `id` идентификатор строится из названия: латиница, цифры и дефис, до 40 знаков.

Городов в стартовых списках пять: Астана, Алматы, Шымкент, Караганда, Актобе. В самом файле есть только Астана и Алматы. Администратор может вписать новый город.

Подбор читает только каталог сервиса. Платёжных сервисов нет. Необязательный адрес API хранится в `data/ai.json`, в git не входит и в выдачу карточек не попадает.

## 10. Ограничения

- Каталог учебный: девять записей, а не живая база поставщиков.
- Бронирования, оплаты, уведомлений и личных кабинетов заказчика нет.
- Текст карточки подбора — шаблон с цифрами и полями записи. Проверка отзывов есть только в админке, в счёт не входит и сама не скачивает страницы 2GIS и Instagram.
- Занятость — один период «занят с / занят по», а не список отдельных дат. Пустой период никого не отсекает. Длительность отсекает запись только если у неё задан максимум часов и запрос длиннее.
- В ответе не больше трёх карточек и не больше трёх причин отказа.
- Сессии администратора пропадают после перезапуска.
- Публичная ссылка работает вместе с сервисом и туннелем. Это не отдельный постоянный хостинг.
- Пароль `Astana2026` записан в коде как пароль первого запуска. Дальше действует пароль, сохранённый в панели.

## 11. Ссылка на запущенную версию

- Сервис: [https://sports-flush-saves-condition.trycloudflare.com](https://sports-flush-saves-condition.trycloudflare.com)
- Админ-панель: [https://sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin)

---

# Мердігерлерді ақылды іріктеу

Авторлар: **Alexey Azovskiy** және **Amir Meirmanov**.

## Ашу

| Қайда | Сілтеме |
| --- | --- |
| Сервис | [https://sports-flush-saves-condition.trycloudflare.com](https://sports-flush-saves-condition.trycloudflare.com) |
| Әкімші панелі | [https://sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin) |
| Репозиторий | [https://github.com/BAITC-Hacks/hack-af663e73-sejire](https://github.com/BAITC-Hacks/hack-af663e73-sejire) |

Жария мекенжай — уақытша Cloudflare туннелі. Бет сервис пен туннель істеп тұрғанда ашылады. Әкімші логині: `admin`. Алғашқы құпиясөз: `Astana2026`. Оны панелде ауыстыруға болады.

## 1. Атауы

Мердігерлерді ақылды іріктеу.

## 2. Қысқаша сипаттама

Сервис іс-шара ұйымдастырушысына каталогтан қысқа мердігер тізімін береді. Пайдаланушы қала, күн, ұзақтық, формат, іс-шара сипаты және теңгемен бюджетті көрсетеді. Жауапта ең көбі үш карточка болады: әрқайсысында каталог өрістеріне сүйенген түсініктеме және ашық ұпай бар. Қалған жазбалардың неге өтпегені де көрсетіледі.

Әкімші бөлек кіреді және каталогты бір-бірлеп немесе CSV файлымен толықтырады.

## 3. Не іске асырылған

- Іріктеу формасы: қала, күн, сағатпен ұзақтық, формат, іс-шара сипаты, бюджет, қонақ саны, іс-шара тілі және қызметтер. Ұзақтықты бос қалдыруға болады.
- Қатаң сүзгі. Тізімге қаласы сәйкес, күні бос аралықта және бос емес кезеңнен тыс, форматы, санаты және бюджеті ауқым ішінде болған жазба ғана енеді. Қонақ, тіл, қызметтер және сағат шегінен аспайтын ұзақтық берілсе, олар да тексеріледі.
- Ұпай бойынша сұрыптау: орындалған жұмыс саны мен бюджеттің ауқым ортасына жақындығы. Бірдей сұраныс бірдей рет береді.
- Ең көбі үш карточка. Карточкада атау, түсініктеме және «жұмыс + жақындық = қорытынды» ұпайы бар.
- Салыстыру кестесі және ең көбі үш бас тарту себебі. Себептер әртүрлі түрден алынады: қала, бюджет, күн және әрі қарай.
- Интерфейс пен түсініктемелер орыс, қазақ және ағылшын тілінде. Каталог мәндері сол күйінде сақталады, жазулар аударылады.
- Әкімші панелі: кіру, құпиясөзді ауыстыру, мердігерді қосу және өзгерту, бос емес күндер «бастап» және «дейін», сағат шегі, CSV жүктеу, жолды жою.
- `data/contractors.csv` ішінде тоғыз мердігерден тұратын бастапқы каталог. Әкімші сақтаған жаңа мәндер форма тізімдеріне қосылады.

## 4. Шешім қалай жұмыс істейді

1. `app.py` алғашқы іске қосылғанда `data/contractors.db` SQLite базасын жасайды. База бос болса, жолдар `data/contractors.csv` файлынан оқылады.
2. Браузер `static/index.html` бетін ашып, тізімдерді `GET /api/options` арқылы сұрайды.
3. Пайдаланушы «Іріктеу» түймесін басады. Бет таңдалған өрістермен `GET /api/match` шақырады.
4. Сервер берілген шарттардың бәрінен өткен жазбаларды ғана қалдырады.
5. Қалғаны ұпайдың кемуі бойынша, тең болса атауы бойынша сұрыпталады. Жауапқа алғашқы үшеуі кіреді.
6. Қалғандары үшін әр себеп түрінен бір-бірден, ең көбі үш бас тарту жиналады.
7. Бет карточкаларды, салыстыру кестесін және бас тарту тізімін көрсетеді.

Ұпай былай есептеледі: `жұмыс саны + (1 − |бюджет − ауқым ортасы| / ауқым ені)`. Жақындық 0-ден 1-ге дейін және экранда екі таңбаға дейін дөңгелектенеді.

## 5. Технологиялар

- Python 3, тек стандартты кітапхана: `http.server`, `sqlite3`, `csv`, `json`, `hashlib` (scrypt), `hmac`, `secrets`.
- Беттер — фреймворксыз және жинақсыз HTML, CSS және JavaScript: `static/index.html`, `static/admin.html`.
- Іріктеу модельді шақырмайды: карточка мәтіні каталог өрістерінен үлгімен құралады. Әкімші панелінде API мекенжайын бөлек сақтауға болады. «Проверить отзывы» түймесі сол API-дан нақты мердігер туралы пікір сұрайды және басты беттегі тізімді өзгертпейді. Кілтсіз іріктеу бұрынғыдай жұмыс істейді. Сервис 2GIS пен Instagram беттерін өзі ашпайды.
- Жария мекенжайды Cloudflare Tunnel береді. Қолданбаның өзі Cloudflare-ге сұраныс жібермейді.

## 6. Архитектура

```text
браузер
  static/index.html  →  GET /api/options, GET /api/match
  static/admin.html  →  POST /api/admin/login, /password, /contractors, /import, /delete, /check
        │
        ▼
app.py  (ThreadingHTTPServer)
  search()   сүзгі, ұпай, үш карточка, бас тарту себептері
  sqlite3    data/contractors.db
  csv        data/contractors.csv   (бастапқы толтыру)
  json       data/admin.json        (құпиясөз хеші, алғашқы іске қосу кезінде жасалады)
```

Әкімші сессиясы процесс жадында сақталады: `session` cookie, HttpOnly, SameSite=Lax, 12 сағат. Сервер қайта қосылса, сессия аяқталады. База мен құпиясөз файлы git-ке кірмейді.

Негізгі жолдар:

- `GET /` және `GET /admin` — беттер.
- `GET /api/options?lang=ru|kz|en` — форма тізімдері.
- `GET /api/match` — іріктеу.
- `POST /api/admin/login`, `/logout`, `/password`, `/contractors`, `/import`, `/delete`.

`Procfile` сервисті `python app.py` командасымен қосады. `PORT` айнымалысы берілсе, сервер сол портты тыңдайды. `PORT` болмаса, порт 8080.

## 7. Орнату және іске қосу

Python 3 керек. Бөгде пакет орнату қажет емес.

Репозиторий каталогында:

```powershell
python app.py
```

[Сервисті](https://sports-flush-saves-condition.trycloudflare.com) ашыңыз.

`python` командасы табылмаса, орнатылған Python 3 интерпретаторын іске қосыңыз. Алғашқы іске қосу кезінде консольде `admin` логині және `Astana2026` құпиясөзі шығады. Құпиясөз панелде ауыстырылса, консоль оның өзгергенін жазады.

## 8. Шешімді қалай тексеруге болады

Формада мысал дайын: Астана, 2026-09-23, офлайн, конференция, 1 500 000 тг. «Іріктеу» түймесін басыңыз.

Күтілетін рет:

| Орын | Мердігер | Ұпай |
| --- | --- | --- |
| 1 | Astana Events | 18 + 0.91 = 18.91 |
| 2 | Сарыарка Холл | 11 + 0.83 = 11.83 |
| 3 | Expo Crew | 7 + 1.00 = 8.00 |

Бас тартулар: Алматы Ивент (басқа қала), «Свет до 500 тысяч» (бюджет ауқымнан тыс), «Сцена без окна» (күн аралықтан тыс).

Екінші сынақ: сол қала, күн, формат және бюджет, сипаты — «концерт». Каталогта бұл санат тек Steppe Stage жазбасында бар, сондықтан бір карточка шығады.

Әкімші панелі: [https://sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin), логин `admin`, құпиясөз `Astana2026`. Панелде оны ауыстыруға болады: ағымдағы құпиясөз, жаңасы және қайталау. Жаңа құпиясөз кемінде 6 таңба.

## 9. Деректер және интеграциялар

Іріктеудің жалғыз дереккөзі — сервис каталогы.

`data/contractors.csv` файлы, 9 жол. Бағандар: `id`, `name`, `city`, `categories`, `formats`, `budget_min`, `budget_max`, `available_from`, `available_to`, `done_count`, `capacity`, `languages`, `services`, `busy_from`, `busy_to`, `max_hours`. Ұяшықтағы бірнеше мән `|` арқылы жазылады. Бастапқы файлда бос емес күндер мен сағат шегі бос.

База бос болса, файл `data/contractors.db` ішіне жүктеледі. Одан әрі іріктеу базадан оқиды. CSV 1 МБ-қа дейін, кодтауы UTF-8. `id` бұрыннан бар болса, жол жаңартылады. `id` болмаса, атаудан идентификатор құралады: латиница, сан және дефис, 40 таңбаға дейін.

Бастапқы тізімде бес қала бар: Астана, Алматы, Шымкент, Қарағанды, Ақтөбе. Файлдың өзінде тек Астана мен Алматы бар. Әкімші жаңа қала жаза алады.

Іріктеу тек сервис каталогын оқиды. Төлем сервисі жоқ. Міндетті емес API мекенжайы `data/ai.json` файлында сақталады, git-ке кірмейді және карточкаларға түспейді.

## 10. Шектеулер

- Каталог оқу үлгісі: тоғыз жазба, тірі жеткізуші базасы емес.
- Брондау, төлем, хабарлама және тапсырыс беруші кабинеті жоқ.
- Іріктеу карточкасының мәтіні — осы жазбаның сандары мен өрістері бар үлгі. Пікірді тексеру тек әкімші панелінде, ұпайға кірмейді және 2GIS пен Instagram беттерін өзі жүктемейді.
- Бос емес күндер жеке тізім емес, бір «бастап / дейін» кезеңі. Бос кезең ешкімді шығармайды. Ұзақтық жазбаны тек сағат шегі беріліп, сұраныс одан ұзақ болса ғана шығарады.
- Жауапта үш карточкадан және үш бас тарту себебінен артық болмайды.
- Әкімші сессиясы сервер қайта қосылғанда жойылады.
- Жария сілтеме сервиспен және туннельмен бірге жұмыс істейді. Бұл бөлек тұрақты хостинг емес.
- `Astana2026` құпиясөзі алғашқы іске қосу құпиясөзі ретінде кодта жазылған. Одан әрі панелде сақталған құпиясөз қолданылады.

## 11. Іске қосылған нұсқаға сілтеме

- Сервис: [https://sports-flush-saves-condition.trycloudflare.com](https://sports-flush-saves-condition.trycloudflare.com)
- Әкімші панелі: [https://sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin)

---

# Smart contractor matching

Authors: **Alexey Azovskiy** and **Amir Meirmanov**.

## Open

| Where | Link |
| --- | --- |
| Service | [https://sports-flush-saves-condition.trycloudflare.com](https://sports-flush-saves-condition.trycloudflare.com) |
| Admin panel | [https://sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin) |
| Repository | [https://github.com/BAITC-Hacks/hack-af663e73-sejire](https://github.com/BAITC-Hacks/hack-af663e73-sejire) |

The public address is a temporary Cloudflare tunnel. The page stays available while the service and the tunnel are running. Admin login: `admin`. First password: `Astana2026`. It can be changed in the panel.

## 1. Name

Smart contractor matching.

## 2. Short description

The service gives an event organizer a short list of contractors from a catalog. The user sets a city, date, duration, format, kind of event, and budget in tenge. The answer contains at most three cards. Each card has an explanation tied to catalog fields and an open score. The page also shows why other records failed the conditions.

An administrator signs in separately and adds contractors one by one or from a CSV file.

## 3. What is implemented

- A matching form: city, date, duration in hours, format, kind of event, budget, guest count, event language, and services. Duration can be left empty.
- A hard filter. A record is listed only when the city matches, the date is inside the open window and outside the busy period, and the format, category, and budget range match. Services, language, capacity, and a duration within the hour limit are checked when the user sets them.
- Ranking by score: completed jobs plus how close the budget is to the middle of the range. The same query always returns the same order.
- At most three cards. A card shows the name, the explanation, and a score in the form “jobs + fit = total”.
- A comparison table and up to three rejection reasons, one for each kind: city, budget, date, and so on.
- Interface and explanation text in Russian, Kazakh, and English. Catalog values stay as stored; their labels are translated.
- An admin panel: sign-in, password change, add and edit a contractor, busy dates from and until, an hour limit, CSV upload, and row delete.
- A starter catalog of nine contractors in `data/contractors.csv`. Values saved by the administrator show up in the form lists.

## 4. How the solution works

1. On the first run, `app.py` creates the SQLite database `data/contractors.db`. If it is empty, rows are read from `data/contractors.csv`.
2. The browser opens `static/index.html` and loads the lists from `GET /api/options`.
3. The user presses “Match”. The page calls `GET /api/match` with the selected fields.
4. The server keeps only the records that pass every stated condition.
5. The rest are sorted by score descending, then by name. The response contains the first three.
6. Up to three rejections are collected for the others, one per reason kind.
7. The page shows the cards, the comparison table, and the rejection list.

The score is `completed jobs + (1 − |budget − range center| / range width)`. The fit is from 0 to 1 and is shown rounded to two decimals.

## 5. Technologies

- Python 3, standard library only: `http.server`, `sqlite3`, `csv`, `json`, `hashlib` (scrypt), `hmac`, `secrets`.
- Pages are HTML, CSS, and JavaScript with no framework and no build step: `static/index.html`, `static/admin.html`.
- Matching does not call a model: card text is a template filled from the catalog row. The admin panel can store an API address separately. “Проверить отзывы” asks that API about one contractor and does not change the public list. Without a key, matching works as before. The service does not open 2GIS or Instagram itself.
- The public address is served by a Cloudflare Tunnel. The application itself does not call Cloudflare.

## 6. Architecture

```text
browser
  static/index.html  →  GET /api/options, GET /api/match
  static/admin.html  →  POST /api/admin/login, /password, /contractors, /import, /delete, /check
        │
        ▼
app.py  (ThreadingHTTPServer)
  search()   filter, score, three cards, rejection reasons
  sqlite3    data/contractors.db
  csv        data/contractors.csv   (initial load)
  json       data/admin.json        (password hash, created on first run)
```

The admin session lives in process memory: a `session` cookie, HttpOnly, SameSite=Lax, 12 hours. Restarting the server ends the session. The database and the password file are not in git.

Main paths:

- `GET /` and `GET /admin` — pages.
- `GET /api/options?lang=ru|kz|en` — form lists.
- `GET /api/match` — matching.
- `POST /api/admin/login`, `/logout`, `/password`, `/contractors`, `/import`, `/delete`.

The `Procfile` starts the service with `python app.py`. If `PORT` is set, the server listens on that port. Without `PORT`, the port is 8080.

## 7. Install and run

Python 3 is required. No third-party packages need to be installed.

From the repository directory:

```powershell
python app.py
```

Open the [service](https://sports-flush-saves-condition.trycloudflare.com).

If the `python` command is not found, start the installed Python 3 interpreter. On the first run the console prints the login `admin` and the password `Astana2026`. After a change in the panel, the console says the password was changed.

## 8. How to check the solution

The form is already filled with the example: Astana, 2026-09-23, in person, conference, 1,500,000 KZT. Press “Match”.

Expected order:

| Place | Contractor | Score |
| --- | --- | --- |
| 1 | Astana Events | 18 + 0.91 = 18.91 |
| 2 | Сарыарка Холл | 11 + 0.83 = 11.83 |
| 3 | Expo Crew | 7 + 1.00 = 8.00 |

Rejections: Алматы Ивент (another city), «Свет до 500 тысяч» (budget outside the range), «Сцена без окна» (date outside the window).

Second run: the same city, date, format, and budget, with the kind set to “concert” (`концерт`). In the catalog only Steppe Stage has that category, so the result is one card.

Admin panel: [https://sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin), login `admin`, password `Astana2026`. It can be changed in the panel: current password, new password, and a repeat. The new password is at least 6 characters.

## 9. Data and integrations

The only source for matching is the service catalog.

`data/contractors.csv` has 9 rows. Columns: `id`, `name`, `city`, `categories`, `formats`, `budget_min`, `budget_max`, `available_from`, `available_to`, `done_count`, `capacity`, `languages`, `services`, `busy_from`, `busy_to`, `max_hours`. Several values in one cell are separated by `|`. Busy dates and the hour limit are empty in the starter file.

An empty database is loaded from that file into `data/contractors.db`. Matching then reads the database. A CSV upload is limited to 1 MB and must be UTF-8. An existing `id` updates the row. Without an `id`, the identifier is built from the name: Latin letters, digits, and hyphens, up to 40 characters.

The starter lists contain five cities: Astana, Almaty, Shymkent, Karaganda, and Aktobe. The file itself contains only Astana and Almaty. An administrator can type a new city.

Matching reads only the service catalog. There is no payment service. An optional API address is stored in `data/ai.json`, is not in git, and is not used in the cards.

## 10. Limitations

- The catalog is a sample of nine records, not a live supplier database.
- There is no booking, payment, notification, or customer account.
- Public card text is a template filled with that record’s numbers and fields. The review check exists only in the admin panel, does not affect the score, and does not download 2GIS or Instagram pages.
- A busy period is one range, “busy from / busy until”, not a list of separate dates. An empty period excludes nobody. Duration excludes a record only when that record has an hour limit and the request is longer.
- A response has at most three cards and at most three rejection reasons.
- Admin sessions disappear when the server restarts.
- The public link stays up together with the service and the tunnel. It is not a separate permanent host.
- The password `Astana2026` is stored in the code as the first-run password. After that, the password saved in the panel is the one that works.

## 11. Link to the running version

- Service: [https://sports-flush-saves-condition.trycloudflare.com](https://sports-flush-saves-condition.trycloudflare.com)
- Admin panel: [https://sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin)

# Умный подбор подрядчиков

Авторы: Alexey Azovskiy, Amir Meirmanov.

Репозиторий: [github.com/BAITC-Hacks/hack-af663e73-sejire](https://github.com/BAITC-Hacks/hack-af663e73-sejire).

Публичный адрес [sports-flush-saves-condition.trycloudflare.com](https://sports-flush-saves-condition.trycloudflare.com) — временный туннель Cloudflare, а не постоянный хостинг. Страница открывается, только пока запущены сервис и туннель. Админ-панель: [sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin).

Сервис рекомендует подрядчиков по анонимизированному каталогу. Бронирования, оплаты, уведомлений подрядчикам и личных кабинетов заказчиков нет. Внешние API, языковые модели и ключи не используются.

## Данные

В `data/contractors.csv` 66 профилей. Колонки:

`id`, `anon_name`, `categories`, `city`, `city_imputed`, `synthetic`, `price_from_kzt`, `price_imputed`, `event_formats`, `languages`, `max_hours`, `busy_dates`, `description`.

- `categories` — кто подрядчик.
- `event_formats` — для каких событий он работает: свадьба, той, корпоратив, конференция, юбилей, день рождения.
- `languages` — язык работы: русский, казахский, английский.
- `city` — Алматы, Астана или Зарубежье.
- `price_from_kzt` — цена «от» в тенге, не вилка.
- `max_hours` — максимум часов на площадке. Пустое значение значит, что ограничение по присутствию неприменимо.
- `busy_dates` — конкретные занятые даты в диапазоне 23.09.2026–31.12.2026, через `|`.
- `synthetic`, `city_imputed`, `price_imputed` — признаки синтетического профиля или значения, проставленного при подготовке датасета.

Поля вроде числа выполненных работ, вместимости гостей и бюджетной вилки в каталоге нет, и подбор их не использует. Если цена пустая, профиль не называется подходящим по бюджету: он остаётся в списке отказов с причиной «цена не указана».

## Как устроен подбор

Форма принимает город, дату, тип мероприятия, категорию подрядчика, бюджет в тенге и необязательные длительность и язык.

В результаты попадает только профиль, у которого:

- город совпадает;
- выбранная категория есть в `categories`;
- выбранный тип есть в `event_formats`;
- цена известна и `price_from_kzt` не выше бюджета;
- выбранной даты нет в `busy_dates`;
- если язык задан, он есть в `languages`;
- если длительность задана и `max_hours` не пустой, лимит не меньше этой длительности.

Пустой `max_hours` по длительности никого не отсекает.

Ответ содержит не больше трёх карточек. Порядок детерминированный: наименьшая цена «от», при равной цене — `id`. Это порядок по цене, не оценка качества. Над карточками написано, сколько профилей прошло фильтр и сколько показано. Если город не содержит выбранной категории, исход отдельный: указано, в каких других городах категория есть. Если категория в городе есть, но никто не прошёл, перечислены все отказы и причина каждого: формат, неизвестная цена, бюджет, занятая дата, язык или длительность.

Текст карточки собирается из полей этого профиля и параметров запроса: город, категория, цена относительно бюджета, тип, точная дата, языки, лимит часов. Первое предложение описания добавляется как цитата. Для синтетического профиля и для восстановленных города или цены добавляется явная пометка. Восстановленная цена не выдаётся за подтверждённую.

Интерфейс подбора и админки переключается на русский, казахский и английский. Названия значений каталога остаются такими, как они записаны в данных; подписи полей переводятся.

## Запуск и пароль администратора

Нужен Python 3 из стандартной библиотеки. Зависимости не ставятся.

```
python app.py
```

Порт берётся из переменной `PORT`, адрес — из `HOST`.

Пароля в коде и в журнале нет. При первом запуске, если файла `data/admin.json` ещё нет, задайте переменные окружения и не добавляйте их в git:

- `ADMIN_PASSWORD` — не короче 6 символов;
- `ADMIN_USER` — необязательно, по умолчанию `admin`.

`data/admin.json` хранит только соль и хеш scrypt. Если файл уже есть, сервис его не перезаписывает и пароль не печатает. Смена пароля есть в панели: текущий, новый и повтор.

Вход ограничен: больше 8 неудачных попыток с одного адреса за 10 минут получают отказ. Счётчик хранится в памяти процесса и сбрасывается при перезапуске. Сессия тоже в памяти, cookie `session` стоит 12 часов, с флагами `HttpOnly` и `SameSite=Lax`. Флаг `Secure` добавляется, когда запрос пришёл по HTTPS. Изменения в админке принимаются только с заголовком `X-Requested-With: fetch` и с `Origin`, совпадающим с адресом сервиса. Запросы к базе параметризованы.

## Каталог

В админке можно добавить один профиль, изменить его и удалить после подтверждения. Новая запись без `id` сохраняется как синтетическая.

CSV загружается в два шага. После выбора файла показывается предпросмотр: какие строки будут добавлены, какие обновлены, какие пропущены как повтор `id` или ошибка. Запись начинается только после подтверждения. Повторный импорт той же строки с тем же `id` обновляет её и не создаёт копию. Поддерживаются UTF-8 с BOM, кавычки, запятые и переносы внутри полей. Флаги и `busy_dates` сохраняются. Если при разборе файла возникает ошибка строки, она попадает в отчёт и не записывается; уже разобранные корректные строки этой загрузки сохраняются вместе с отчётом. Неожиданный сбой откатывает транзакцию загрузки, открытой этим запросом.

После добавления и импорта списки городов и категорий на главной читаются из каталога заново.

## Проверенные запросы

Кнопки на главной повторяют эти четыре запроса по загруженным 66 профилям.

1. Плотная категория. Алматы, 14.10.2026, корпоратив, ведущий, бюджет 1 500 000. В городе 10 ведущих, проходят 7. Показаны три с наименьшей ценой: Куррапика, 500 000 тг, `HK-88430`; Мицури Канроджи, 650 000 тг, `HK-44923`; Кики, 900 000 тг, `HK-35215`. Дороже и тоже проходят Сон Гоку, Буллма, Хаул и Джинбей. Не проходят Аня Форджер (дата занята), Софи Хаттер (цена от 2 000 000 тг) и Эмилия (нет формата «корпоратив»).
2. Редкая категория. Алматы, 14.10.2026, свадьба, флорист, бюджет 500 000. В городе 2 флориста, проходит 1: Тихиро Огино, 250 000 тг, `HK-90001`, синтетический профиль, лимит часов пустой. Тони Тони Чоппер не проходит: 14.10.2026 есть в занятых датах.
3. Тот же запрос, что в пункте 1, но дата 12.12.2026. Категория в городе есть, проходят 0 из 10. У восьми дата занята, у Софи Хаттер цена выше бюджета, у Эмилии нет формата «корпоратив».
4. Пустой результат другого вида. Астана, 14.11.2026, конференция, ресторан, бюджет 2 000 000. В Астане ресторанов нет. Категория есть в Алматы.

Повтор любого из этих запросов возвращает тот же набор и тот же порядок.

## Ограничения

Каталог анонимный и покрывает занятость только внутри своего диапазона дат. Цитата в карточке — первое предложение описания, не отдельный отзыв. Сортировка не измеряет качество. Синтетические профили и восстановленные город или цена помечены и не выдаются за подтверждённые сведения. Туннель Cloudflare временный. Сессии и счётчик входа не переживают перезапуск процесса.

## Проверки

```
python -m unittest test_match.py
```

Файл `test_match.py` проверяет загрузку 66 строк и флаги, фильтры, устойчивый порядок по цене и `id`, различие «категории нет» и «все отсеяны», занятые даты, пустой лимит часов, неизвестную цену, импорт исходной схемы CSV, сохранение флагов и обновление по тому же `id`.

---

# Мердігерлерді ақылды іріктеу

Авторлар: Alexey Azovskiy, Amir Meirmanov.

Репозиторий: [github.com/BAITC-Hacks/hack-af663e73-sejire](https://github.com/BAITC-Hacks/hack-af663e73-sejire).

Жария мекенжай [sports-flush-saves-condition.trycloudflare.com](https://sports-flush-saves-condition.trycloudflare.com) — тұрақты хостинг емес, уақытша Cloudflare туннелі. Бет сервис пен туннель істеп тұрғанда ғана ашылады. Әкімші панелі: [sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin).

Сервис анонимді каталог бойынша мердігер ұсынады. Брондау, төлем, мердігерге хабарлама және тапсырыс берушінің жеке кабинеті жоқ. Сыртқы API, тілдік модель және кілт қолданылмайды.

## Деректер

`data/contractors.csv` файлында 66 профиль. Бағандар:

`id`, `anon_name`, `categories`, `city`, `city_imputed`, `synthetic`, `price_from_kzt`, `price_imputed`, `event_formats`, `languages`, `max_hours`, `busy_dates`, `description`.

- `categories` — мердігер кім.
- `event_formats` — қай іс-шараға жұмыс істейді: свадьба, той, корпоратив, конференция, юбилей, день рождения.
- `languages` — жұмыс тілі: русский, казахский, английский.
- `city` — Алматы, Астана немесе Зарубежье.
- `price_from_kzt` — теңгедегі бастапқы баға, аралық емес.
- `max_hours` — алаңдағы сағат шегі. Бос мән шектеу қолданылмайтынын білдіреді.
- `busy_dates` — 23.09.2026–31.12.2026 аралығындағы нақты бос емес күндер, `|` арқылы.
- `synthetic`, `city_imputed`, `price_imputed` — синтетикалық профиль немесе дайындау кезінде қойылған мән.

Орындалған жұмыс саны, қонақ сыйымдылығы және бюджет аралығы каталогта жоқ, іріктеу оларды қолданбайды. Баға бос болса, профиль бюджетке сай деп аталмайды: ол «баға көрсетілмеген» себебімен бас тарту тізімінде қалады.

## Іріктеу қалай жұмыс істейді

Пішін қала, күн, іс-шара түрі, мердігер санаты, теңгедегі бюджет және міндетті емес ұзақтық пен тілді қабылдайды.

Нәтижеге тек мына шарттардың бәрі орындалған профиль кіреді:

- қала сәйкес;
- таңдалған санат `categories` ішінде;
- таңдалған түрі `event_formats` ішінде;
- баға белгілі және `price_from_kzt` бюджеттен аспайды;
- таңдалған күн `busy_dates` ішінде жоқ;
- тіл берілсе, ол `languages` ішінде бар;
- ұзақтық берілсе және `max_hours` бос болмаса, шек осы ұзақтықтан кем емес.

Бос `max_hours` ұзақтық бойынша ешкімді шығармайды.

Жауапта ең көбі үш карточка. Рет тұрақты: ең төмен бастапқы баға, баға тең болса `id`. Бұл баға реті, сапа бағасы емес. Карточкалардың үстінде фильтрден қанша профиль өткені және қаншасы көрсетілгені жазылады. Қалада таңдалған санат болмаса, ол басқа нәтиже: санат қай қалаларда бар екені көрсетіледі. Санат қалада бар, бірақ ешкім өтпесе, барлық бас тарту және әрқайсының себебі тізіледі: формат, белгісіз баға, бюджет, бос емес күн, тіл немесе ұзақтық.

Карточка мәтіні осы профиль өрістері мен сұрау параметрлерінен құралады: қала, санат, бюджетке қатысты баға, түрі, нақты күн, тілдер, сағат шегі. Сипаттаманың бірінші сөйлемі дәйексөз ретінде қосылады. Синтетикалық профильге және қалпына келтірілген қалаға немесе бағаға анық белгі қойылады. Қалпына келтірілген баға расталған баға ретінде көрсетілмейді.

Іріктеу және әкімші интерфейсі орысша, қазақша және ағылшынша ауысады. Каталог мәндері деректе жазылғанындай қалады, өріс атаулары аударылады.

## Іске қосу және әкімші құпиясөзі

Python 3 және стандартты кітапхана жеткілікті. Тәуелділік орнатылмайды.

```
python app.py
```

Порт `PORT` айнымалысынан, мекенжай `HOST` айнымалысынан алынады.

Құпиясөз кодта да, журналда да жоқ. `data/admin.json` файлы әлі жоқ алғашқы іске қосуда орта айнымалыларын беріңіз және оларды git-ке қоспаңыз:

- `ADMIN_PASSWORD` — кемінде 6 таңба;
- `ADMIN_USER` — міндетті емес, әдепкісі `admin`.

`data/admin.json` тек scrypt тұзы мен хешін сақтайды. Файл бар болса, сервис оны қайта жазбайды және құпиясөзді басып шығармайды. Құпиясөзді панелде ауыстыруға болады: ағымдағы, жаңа және қайталау.

Кіру шектелген: бір мекенжайдан 10 минутта 8-ден артық сәтсіз әрекет қабылданбайды. Есептегіш процесс жадында және қайта қосу кезінде тазаланады. Сессия да жадта, `session` cookie 12 сағат, `HttpOnly` және `SameSite=Lax`. `Secure` сұрау HTTPS арқылы келсе қосылады. Әкімші өзгерістері тек `X-Requested-With: fetch` тақырыбымен және сервис мекенжайына сәйкес `Origin` болса қабылданады. База сұраулары параметрленген.

## Каталог

Әкімші панелінде бір профиль қосуға, өзгертуге және растаудан кейін жоюға болады. `id` жоқ жаңа жазба синтетикалық болып сақталады.

CSV екі қадаммен жүктеледі. Файл таңдалған соң алдын ала қарау шығады: қай жолдар қосылады, қайсысы жаңартылады, қайсысы қайталанған `id` немесе қате ретінде өткізіледі. Жазу тек растаудан кейін басталады. Сол `id` бар жолды қайта импорттау оны жаңартады және көшірме жасамайды. BOM бар UTF-8, тырнақша, үтір және өріс ішіндегі жол ауыстыру қолдау табады. Белгілер мен `busy_dates` сақталады. Жол қатесі есепке түседі және жазылмайды; осы жүктеудің дұрыс жолдары есеппен бірге сақталады. Күтпеген ақау осы сұрау ашқан транзакцияны кері қайтарады.

Қосқаннан және импорттан кейін басты беттегі қала мен санат тізімдері каталогтан қайта оқылады.

## Тексерілген сұраулар

Басты беттегі түймелер жүктелген 66 профиль бойынша осы төрт сұрауды қайталайды.

1. Жиі санат. Алматы, 14.10.2026, корпоратив, ведущий, бюджет 1 500 000. Қалада 10 жүргізуші, 7-еуі өтеді. Ең төмен бағамен үшеуі көрсетіледі: Куррапика, 500 000 тг, `HK-88430`; Мицури Канроджи, 650 000 тг, `HK-44923`; Кики, 900 000 тг, `HK-35215`. Қымбатырақ, бірақ өтетіндер: Сон Гоку, Буллма, Хаул, Джинбей. Өтпейтіндер: Аня Форджер (күн бос емес), Софи Хаттер (бастапқы баға 2 000 000 тг), Эмилия («корпоратив» түрі жоқ).
2. Сирек санат. Алматы, 14.10.2026, свадьба, флорист, бюджет 500 000. Қалада 2 флорист, 1-еуі өтеді: Тихиро Огино, 250 000 тг, `HK-90001`, синтетикалық профиль, сағат шегі бос. Тони Тони Чоппер өтпейді: 14.10.2026 бос емес күндерде бар.
3. 1-тармақтағы сұрау, бірақ күні 12.12.2026. Санат қалада бар, 10-нан 0-і өтеді. Сегізінің күні бос емес, Софи Хаттердің бағасы бюджеттен жоғары, Эмилияда «корпоратив» түрі жоқ.
4. Басқа бос нәтиже. Астана, 14.11.2026, конференция, ресторан, бюджет 2 000 000. Астанада мейрамхана жоқ. Санат Алматыда бар.

Осы сұраулардың кез келгенін қайталау сол жиынды және сол ретті береді.

## Шектеулер

Каталог анонимді және бос емес күндерді тек өз күн аралығында көрсетеді. Карточкадағы дәйексөз — сипаттаманың бірінші сөйлемі, бөлек пікір емес. Сұрыптау сапаны өлшемейді. Синтетикалық профильдер және қалпына келтірілген қала немесе баға белгіленеді және расталған дерек ретінде берілмейді. Cloudflare туннелі уақытша. Сессия мен кіру есептегіші процесті қайта қосқанда сақталмайды.

## Тексерулер

```
python -m unittest test_match.py
```

`test_match.py` 66 жол мен белгілердің жүктелуін, фильтрлерді, баға мен `id` бойынша тұрақты ретті, «санат жоқ» пен «бәрі шығарылды» айырмасын, бос емес күндерді, бос сағат шегін, белгісіз бағаны, бастапқы CSV схемасының импортын, белгілердің сақталуын және сол `id` бойынша жаңартуды тексереді.

---

# Smart contractor matching

Authors: Alexey Azovskiy, Amir Meirmanov.

Repository: [github.com/BAITC-Hacks/hack-af663e73-sejire](https://github.com/BAITC-Hacks/hack-af663e73-sejire).

The public address [sports-flush-saves-condition.trycloudflare.com](https://sports-flush-saves-condition.trycloudflare.com) is a temporary Cloudflare tunnel, not permanent hosting. The page is available only while the service and the tunnel are running. Admin panel: [sports-flush-saves-condition.trycloudflare.com/admin](https://sports-flush-saves-condition.trycloudflare.com/admin).

The service recommends contractors from an anonymized catalog. There is no booking, payment, contractor notification, or customer account. No external API, language model, or key is used.

## Data

`data/contractors.csv` has 66 profiles. Columns:

`id`, `anon_name`, `categories`, `city`, `city_imputed`, `synthetic`, `price_from_kzt`, `price_imputed`, `event_formats`, `languages`, `max_hours`, `busy_dates`, `description`.

- `categories` is who the contractor is.
- `event_formats` is which events they work: свадьба, той, корпоратив, конференция, юбилей, день рождения.
- `languages` is the working language: русский, казахский, английский.
- `city` is Алматы, Астана, or Зарубежье.
- `price_from_kzt` is a starting price in tenge, not a range.
- `max_hours` is the maximum hours on site. An empty value means a presence limit does not apply.
- `busy_dates` lists individual busy dates from 23.09.2026 to 31.12.2026, separated by `|`.
- `synthetic`, `city_imputed`, and `price_imputed` mark a synthetic profile or a value filled while the dataset was prepared.

Completed-job counts, guest capacity, and budget ranges are not in the catalog and are not used for matching. If the price is empty, the profile is not described as fitting the budget: it stays in the rejection list with the reason that the price is not stated.

## How matching works

The form takes a city, a date, an event type, a contractor category, a budget in tenge, and optional duration and language.

A profile is recommended only when:

- the city matches;
- the chosen category is in `categories`;
- the chosen type is in `event_formats`;
- the price is known and `price_from_kzt` is not above the budget;
- the chosen date is not in `busy_dates`;
- if a language is set, it is in `languages`;
- if a duration is set and `max_hours` is not empty, the limit is at least that duration.

An empty `max_hours` does not reject anyone for duration.

The response has at most three cards. The order is deterministic: lowest starting price, then `id` when prices are equal. This is a price order, not a quality score. Above the cards the page states how many profiles passed and how many are shown. If the city has no contractor of the chosen category, that is a separate outcome and the other cities that have the category are named. If the category exists in the city but nobody passed, every rejection is listed with its reason: format, unknown price, budget, busy date, language, or duration.

Card text is built from that profile’s fields and the query: city, category, price against the budget, type, exact date, languages, and hour limit. The first sentence of the description is added as a quotation. A synthetic profile and an imputed city or price get an explicit mark. An imputed price is not presented as confirmed.

The matching page and the admin page switch among Russian, Kazakh, and English. Catalog values stay as stored; field labels are translated.

## Run and admin password

Python 3 and the standard library are enough. Nothing is installed.

```
python app.py
```

The port comes from `PORT` and the address from `HOST`.

There is no password in the code or in the log. On the first run, if `data/admin.json` does not exist yet, set environment variables and do not commit them:

- `ADMIN_PASSWORD`, at least 6 characters;
- `ADMIN_USER`, optional, `admin` by default.

`data/admin.json` stores only a scrypt salt and hash. If the file already exists, the service does not overwrite it and does not print the password. The panel can change it: current password, new password, and a repeat.

Login is limited: more than 8 failed attempts from one address within 10 minutes are rejected. The counter lives in process memory and resets on restart. The session is in memory too. The `session` cookie lasts 12 hours and has `HttpOnly` and `SameSite=Lax`. `Secure` is added when the request arrived over HTTPS. Admin changes are accepted only with the header `X-Requested-With: fetch` and an `Origin` that matches the service address. Database statements are parameterized.

## Catalog

The admin panel can add one profile, edit it, and delete it after confirmation. A new record without an `id` is stored as synthetic.

CSV upload has two steps. After the file is chosen, a preview shows which rows would be added, which would be updated, and which would be skipped as a repeated `id` or an error. Writing starts only after confirmation. Importing the same row with the same `id` updates it and does not create a copy. UTF-8 with BOM, quotes, commas, and line breaks inside fields are supported. Flags and `busy_dates` are kept. A bad row is reported and not written; the valid rows of that upload are saved together with the report. An unexpected failure rolls back the transaction opened by that request.

After an add or an import, the city and category lists on the main page are read from the catalog again.

## Checked requests

The buttons on the main page repeat these four requests against the loaded 66 profiles.

1. Dense category. Almaty, 14.10.2026, корпоратив, Ведущий, budget 1 500 000. The city has 10 hosts and 7 pass. The three lowest prices are shown: Куррапика, 500 000 KZT, `HK-88430`; Мицури Канроджи, 650 000 KZT, `HK-44923`; Кики, 900 000 KZT, `HK-35215`. Сон Гоку, Буллма, Хаул, and Джинбей also pass at higher prices. Аня Форджер is busy, Софи Хаттер starts at 2 000 000 KZT, and Эмилия has no корпоратив format.
2. Rare category. Almaty, 14.10.2026, свадьба, Флорист, budget 500 000. The city has 2 florists and 1 passes: Тихиро Огино, 250 000 KZT, `HK-90001`, a synthetic profile with an empty hour limit. Тони Тони Чоппер does not pass: 14.10.2026 is in the busy dates.
3. The same request as item 1, but on 12.12.2026. The category exists in the city and 0 of 10 pass. Eight are busy, Софи Хаттер is above the budget, and Эмилия has no корпоратив format.
4. A different empty result. Astana, 14.11.2026, конференция, Ресторан, budget 2 000 000. Astana has no restaurants. The category exists in Almaty.

Repeating any of these requests returns the same set in the same order.

## Limitations

The catalog is anonymous and its occupancy covers only its own date range. The quotation on a card is the first sentence of the description, not a separate review. The sort does not measure quality. Synthetic profiles and an imputed city or price are marked and are not presented as confirmed facts. The Cloudflare tunnel is temporary. Sessions and the login counter do not survive a process restart.

## Checks

```
python -m unittest test_match.py
```

`test_match.py` checks loading 66 rows and the flags, the filters, a stable price-then-`id` order, the difference between “no category” and “everyone was rejected”, busy dates, an empty hour limit, an unknown price, import of the original CSV schema, preservation of flags, and an update of the same `id`.

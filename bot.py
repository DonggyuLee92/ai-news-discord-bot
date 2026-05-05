import discord
import os
import feedparser
from openai import OpenAI
from dotenv import load_dotenv
from supabase import create_client
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zoneinfo import ZoneInfo

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
client_ai = OpenAI(api_key=OPENAI_KEY)

scheduler_started = False

RUN_ONCE = os.getenv("RUN_ONCE") == "true"

# 필터 함수
AI_KEYWORDS = [
    "AI",
    "artificial intelligence",
    "OpenAI",
    "GPT",
    "Claude",
    "Gemini",
    "LLM",
    "machine learning",
    "deep learning",
    "neural",
    "agent",
]


def is_ai_news(title):
    title_lower = title.lower()
    return any(keyword.lower() in title_lower for keyword in AI_KEYWORDS)


RSS_FEEDS = [
    "https://techcrunch.com/tag/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://openai.com/blog/rss/",
    "https://ai.googleblog.com/feeds/posts/default",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
]


# 뉴스 함수
def get_ai_news():
    news_list = []
    seen_links = set()

    for url in RSS_FEEDS:
        feed = feedparser.parse(url)

        for entry in feed.entries[:5]:
            if entry.link in seen_links:
                continue

            seen_links.add(entry.link)

            news_list.append(
                {"title": entry.title, "link": entry.link, "description": entry.summary}
            )

    return news_list


# 필터 + 요약 함수
def analyze_news(title, description):
    prompt = f"""
다음 뉴스가 'AI 기술 관련 기사'인지 판단하고, 관련 있다면 한국어로 요약해줘.

[AI 기술 관련 기사 기준]
- AI 모델, LLM, 생성형 AI, 머신러닝, 딥러닝 관련이면 포함
- OpenAI, Anthropic, Google Gemini, Meta AI, NVIDIA AI, AI Agent 관련이면 포함
- AI 서비스, AI 스타트업, AI 규제/정책, AI 반도체도 포함
- 단순 일반 IT 뉴스, 앱 출시, 투자 뉴스인데 AI 기술과 직접 관련이 없으면 제외

[출력 규칙]
- AI 관련 기사면 아래 형식 그대로 작성
- AI 관련 기사가 아니면 정확히 "NO"만 출력

[형식]
🧠 핵심 요약:
- 핵심 내용 2줄

🔥 왜 중요한가:
- 산업/기술 관점에서 1줄

👨‍💻 개발자 관점:
- 개발자가 주목할 포인트 1줄

뉴스:
제목: {title}
내용: {description}
"""

    response = client_ai.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    result = response.choices[0].message.content.strip()

    if result == "NO":
        return None

    return result


def is_already_sent(link):
    response = supabase.table("sent_articles").select("id").eq("link", link).execute()
    return len(response.data) > 0


def save_sent_article(title, link):
    supabase.table("sent_articles").upsert(
        {
            "title": title,
            "link": link,
        },
        on_conflict="link",
    ).execute()


@client.event
async def on_ready():
    global scheduler_started

    print(f"로그인 완료: {client.user}")
    print("RUN_ONCE:", RUN_ONCE)

    if RUN_ONCE:
            print("1회 실행 모드 시작")

            channel = client.get_channel(DISCORD_CHANNEL_ID)

            if channel is None:
                print("채널을 찾지 못했습니다.")
                await client.close()
                return

            await send_news(channel)


            print("1회 실행 완료, 봇 종료")
            await client.close()
            return
    
    if not scheduler_started:
        scheduler = AsyncIOScheduler(timezone=ZoneInfo("Asia/Seoul"))

        scheduler.add_job(
            send_scheduled_news,
            "cron",
            day_of_week="mon-fri",
            hour=9,
            minute=30,
        )

        scheduler.start()
        scheduler_started = True

        print("스케줄러 시작됨: 평일 오전 9시 30분")


async def send_news(channel):
    news = get_ai_news()

    # count = 0

    for item in news:
        title = item["title"]
        link = item["link"]
        description = item.get("description") or item.get("summary", "")

        print("검사 시작:", title)

        # 🔥 추가 1 (중복 체크)
        if is_already_sent(link):
            print("이미 보낸 기사라 제외:", title)
            continue

        # 1차 필터 (키워드)
        if not is_ai_news(title):
            print("1차 필터 탈락:", title)
            continue

        print("1차 필터 통과:", title)

        # 2차 필터 + 요약
        summary = analyze_news(title, description)

        if summary is None:
            print("2차 GPT 필터 탈락:", title)
            continue

        print("최종 필터 통과:", title)

        msg = f"""📰 **{title}**

        {summary}

        🔗 {item['link']}"""

        await message.channel.send(msg)

        # 🔥 추가 2 (DB 저장)
        save_sent_article(title, link)

    print("완료")


async def send_scheduled_news():
    channel = client.get_channel(DISCORD_CHANNEL_ID)

    if channel is None:
        print("채널을 찾지 못했습니다.")
        return

    print("평일 9시 30분 자동 뉴스 발송 시작")
    await send_news(channel)


# 디스코드 이벤트
@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content == "!테스트":
        await message.channel.send("봇 정상 작동!")

    if message.content == "!뉴스":
        await send_news(message.channel)

    # count += 1
    # if count >= 3:  # 최대 3개만
    #     break


client.run(TOKEN)

from datetime import datetime

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch

# Load environment variables from .env
load_dotenv()

def get_research_agent():
    """
    Initializes and returns a LangChain agent equipped with Tavily Search.
    """
    # Initialize the Tavily Search tool
    tavily_search = TavilySearch(max_results=5, topic="general")

    # Initialize the OpenAI LLM
    # Note: OPENAI_API_KEY and TAVILY_API_KEY should be in .env
    model = ChatOpenAI(model_name="gpt-4o")

    # Define the system prompt with today's date for better context
    today_date = datetime.today().strftime('%B %d, %Y')
    system_prompt = (
        f"You are a helpful research assistant. Today's date is {today_date}. "
        "Use web search to find accurate, up-to-date information."
    )

    # Create the agent as per documentation
    agent = create_agent(
        model=model,
        tools=[tavily_search],
        system_prompt=system_prompt
    )

    return agent

async def run_research(query: str, history: list[dict] | None = None):
    """
    Runs a research query through the agent and returns the response.
    """
    agent = get_research_agent()

    messages = history or []
    messages.append({"role": "user", "content": query})

    # Invoke the agent using the format from documentation
    response = await agent.ainvoke({
        "messages": messages
    })

    # Extract the response content
    return response["messages"][-1].content

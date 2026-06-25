from bedrock_agentcore import BedrockAgentCoreApp
app = BedrockAgentCoreApp()

from strands import Agent # or bring your agent.

@app.entrypoint
async def handler(request):
    prompt = request.get("prompt")

    agent = Agent()

    async for event in agent.stream_async(prompt):
        yield (event)

app.run()
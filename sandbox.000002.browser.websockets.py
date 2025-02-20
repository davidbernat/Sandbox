import websockets  # requires pip install
import asyncio
import random
import json

# The websockets ws:// protocol differs in that its design is for continuous connection with intermittent data transfers
# sent both ways, whereas https:// is usually used for REST API connections that explicitly expect one sent request to
# receive one received response, at which point the connection is closed. So, the websockets is what is used for
# streaming data one or both ways, from one server potentially sending, broadcasting, and receiving to multiple clients.
# Here we simulate a game engine or content streaming provider that maintains a state (instruction) here on the server,
# and periodically broadcasts that set of state to all its connected clients (once every approximately 0.01 seconds),
# i.e., at about 100 FPS. (It does not contain any optimizations: the state is broadcast again even when the state does
# not change, the entire state is braodcast even when incremental changes of state would be sufficient, etc., but then
# again, managing whether a client has gone off the rails and changed its state in the browser JS is itself an unknown,
# so preserving the 'one state, pave over it all' perspective is itself a design choice.) The key insight here is how
# the use of the canvas allows the render to be reduced to a small dictionary of parameters for each element, which is
# for all intents and purposes very simple, extendable, and very fast in modern contexts, so gets you very far for cases
# in which the render is essential but not the whole innovation. The other key insight here is how algorithmic the JS
# can be modeled in one HTML file; enabling generic buttons for communication back to the server, including hotkeys, is
# so simple that the entire frontend is contained in one shareable file with no external dependencies or libraries. On
# the server end, the asynchronous design is modern and the dual consumer/producer handling, so that the server is both
# continuously broadcasting but also adaptive to inbound signals, is challenging to find implemented online elsewhere.
# Lastly, while not implemented here, though hinted at in the HTML, is that small sprite images can be reshaped to their
# desired canvas dimensions, and easily sent as bas64 data URI as 'assets' to a dictionary object in the JS, and then
# triggered to be displayed by render instructions with type="IMAGE" and args=[x, y, ASSET_ID] and a new
# howToRenderInstructionType coded in the JS, and without relying on any external URLs, but maintaining high speeds.
# What this means is that everything from replacing the background to an image of a real-world OpenStreetMap road tile,
# to replacing the blocks of SnakeIQ chasing Corn with Monty Python silly walking gifs chasing Money and Rubber Stamps
# is all a few lines substitution of the same basic render instruction, so this lightweight system takes you very far.


buttons = [dict(key="R", keyboard=["R", "ESCAPE"], text="[R]EARRANGE", visible=True),]
constructs = [
    dict(type="LABEL", text="This is a label.", id="LABEL", style="color: green;"),
    dict(type="CANVAS", id="PRIMARY", size=[640, 400], style="border: 1px solid orange"),
    dict(type="BUTTONS", id="BUTTONS", buttons=buttons, style=f"width: 640px")
]
construction = dict(metadata=dict(title="TITLE"),
                    constructions=constructs)


def generate_random_items():
    n_items = random.randint(1, 10)
    to_render = []
    for i in range(n_items):
        xy = [random.uniform(0, 640-10), random.uniform(0, 400-10)]
        to_render.append(dict(type="RECTANGLE", into="PRIMARY", fid="fBLOCK_{i}", xy=xy, args=[10, 10, "white"]))
    to_render.append(dict(type="TEXT", into="PRIMARY", fid="COUNT", xy=(260, 160), args=[f"n_items={n_items}", "left", "20px", "white"]))
    return to_render


instructions = generate_random_items()


async def producer_handler(websocket):
    while True:
        data = dict(assets=[], instructions=instructions)  # get the global variable holding instructions
        await websocket.send(json.dumps(dict(message=f"update gameplay", data=data)))
        try: await asyncio.wait_for(consumer_handler(websocket), timeout=0.01)
        except TimeoutError: pass
        except Exception as e: raise RuntimeError(e)


async def consumer_handler(websocket):
    message = await websocket.recv()
    print(f"Received: {message}")
    try:
        browser_id, key = message.split(".")
        if key == "R":  # the key of the button, whether R or ESCAPE is pressed, or the button itself is clicked.
            global instructions
            instructions = generate_random_items()  # generate new items
    except Exception as e:
        return


# When a user connects to ws://localhost:8765 the handler is enacted to send the welcome message, which is used here
# to pass 'construction' information on how the JS can add HTML elements via divs, canvas, buttons. It constructs once.
# Then, producer_handler begins, which simply waits for timeout=0.01 seconds to identity whether any inbound websocket
# message was received (i.e., a message of any button press). Regardless of whether a message was received or not, the
# producer_handler broadcasts its present state of elements which should be rendered (which we refer to as instructions)
# to show that the communication can be structured as a set of machine instructions for remote execution; our internal
# websockets communication channel expects logging of each instruction action, its failures, and communication of those
# back to the source, i.e., like assembly. This is a benefit of the structured instruction rendering code model here.
async def handler(websocket):
    await websocket.send(json.dumps(dict(message="Welcome to the game.", data=construction)))
    await producer_handler(websocket)


async def main():
    async with websockets.serve(handler, "localhost", 8765) as server:
        print("starting service on port 8765")
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())

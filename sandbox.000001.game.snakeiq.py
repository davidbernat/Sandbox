from collections import namedtuple
import pygame
import random
import enum
import time

# This SnakeIQ builds a classic version of the phone game Snake (originally 1976 Blockade) on top of the PyGame Python
# engine. (Our internal version moved away from dependencies on pygame and integrated display into a browser through
# HTML and websockets, and the pygame package is only otherwise used for the clock function to regulate update intervals
# and input function to recognize keypress actions.) The insights here are the object encapsulation of the objects in
# the game and its rendering, although the game logic for modifying the game objects' states (i.e. position and
# orientation) are still in the game loop instead of refactored to belong to the objects themselves as methods. The
# internal version is designed to place any number of objects on any number of canvases, with each of their logics' on
# the objects themselves, such that a brain algorithm can be embedded directly into the object to make its own decisions
# or receive human inputs, and all collisions handled by hit boxes implicit between pairwise combinations of objects so
# that all state updates, decision support, and rendering are individual to the object, on top of a generic game engine.
# The logic of the SnakeIQ game itself is then simply the spawning, how an action changes its state, and what to do when
# certain pair-wise collisions occur (i.e., update the involved snake state to done or to grow, for instance). The same
# basic structure can build thousands of games including Asteroids, Ants Foraging, or overlay on images such as a game
# of SnakeIQ playing out on streets of an OpenStreetMap map, or even rendering as a low-feature image based web browser.



Coordinate = namedtuple('Coordinate', 'lat, lng')


class Orientation(enum.Enum):
    EAST = 1
    WEST = 2
    NORTH = 3
    SOUTH = 4


WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
LIGHT_BLUE = (0, 200, 255)
LIGHT_YELLOW = (255, 231, 82)

ROYAL_PURPLE = "#59467B"
ROYAL_MAHOGANY = "#653420"
MONEY_GOLD = "#3FFD98E"  # caramel
MONEY_GREEN = "#91BA6F"

DISPLAY_NAME = "SnakeIQ"
DISPLAY_SIZE = (640, 480)
BLOCK_SIZE = 20
FONT_SIZE = 20
FPS = 10

pygame.init()
font = pygame.font.Font(None, FONT_SIZE)


class Snake:
    # merging object criteria (i.e., location) with object worthiness (i.e., score)

    def __init__(self, at=None, length=3):
        if at is None : at = (40+length*BLOCK_SIZE, 40)
        self.elements = [Coordinate(at[0]-i*BLOCK_SIZE, at[1]) for i in range(length)]
        self.orientation = Orientation.EAST
        self.growing = 0

        self.score = length
        self.born_ts = time.time()

    def draw(self, screen):
        body = Square()
        for c in self.elements: screen.blit(body.image, (c.lat, c.lng))


class Food:

    def __init__(self, at=None, value=1):
        if at is None: at = Coordinate(BLOCK_SIZE*random.randint(0, DISPLAY_SIZE[0]//BLOCK_SIZE-1),
                                       BLOCK_SIZE*random.randint(0, DISPLAY_SIZE[1]//BLOCK_SIZE-1))
        self.at = at
        self.value = value

    def draw(self, screen):
        screen.blit(Square(fill=LIGHT_YELLOW).image, (self.at.lat, self.at.lng))


class Game:

    def __init__(self):
        self.screen = pygame.display.set_mode(DISPLAY_SIZE)
        pygame.display.set_caption(DISPLAY_NAME)
        self.clock = pygame.time.Clock()
        self.frame = []
        self.game_over = False
        self.reason = None

        self.snakes = [Snake()]
        self.foods = [Food()]

    def loop(self):
        while not self.game_over:
            self.interpret_events()
            self.update_state()
            self.interpret_interactions()
            self.update_ui()

    def update_ui(self):
        self.screen.fill(BLACK)
        for snake in self.snakes: snake.draw(self.screen)
        for food in self.foods: food.draw(self.screen)

        for i, snake in enumerate(self.snakes):
            text = font.render(f"{i} Snake: {snake.score}", True, WHITE)
            self.screen.blit(text, (0, BLOCK_SIZE*i))
        pygame.display.flip()
        self.clock.tick(FPS)

    def update_state(self):
        # passive
        for snake in self.snakes:
            head_is = snake.elements[0]
            match snake.orientation:
                case Orientation.EAST:
                    head_to = Coordinate(head_is.lat + BLOCK_SIZE, head_is.lng)
                case Orientation.WEST:
                    head_to = Coordinate(head_is.lat - BLOCK_SIZE, head_is.lng)
                case Orientation.NORTH:
                    head_to = Coordinate(head_is.lat, head_is.lng - BLOCK_SIZE)
                case Orientation.SOUTH:
                    head_to = Coordinate(head_is.lat, head_is.lng + BLOCK_SIZE)
                case _: raise RuntimeError("impossible")
            snake.elements.insert(0, head_to)
            if snake.growing > 0:
                snake.growing -= 1
            else:
                snake.elements.pop(len(snake.elements)-1)

    def interpret_events(self):
        # not asynchronous; not handling multiple snakes

        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                pygame.quit()
                quit()
            if e.type == pygame.KEYDOWN:
                snake = self.snakes[0]
                if e.key == pygame.K_RIGHT:
                    if snake.orientation != Orientation.WEST:  # prevent humans from stupidly crashing into self
                        self.snakes[0].orientation = Orientation.EAST
                elif e.key == pygame.K_LEFT:
                    if snake.orientation != Orientation.EAST:  # prevent humans from stupidly crashing into self
                        self.snakes[0].orientation = Orientation.WEST
                elif e.key == pygame.K_UP:
                    if snake.orientation != Orientation.SOUTH:  # prevent humans from stupidly crashing into self
                        self.snakes[0].orientation = Orientation.NORTH
                elif e.key == pygame.K_DOWN:
                    if snake.orientation != Orientation.NORTH:  # prevent humans from stupidly crashing into self
                        self.snakes[0].orientation = Orientation.SOUTH

    def interpret_interactions(self):

        # check if collisions
        for s_i, snake in enumerate(self.snakes):
            head_is = snake.elements[0]
            if not DISPLAY_SIZE[0] > head_is.lat >= 0 or not DISPLAY_SIZE[1] > head_is.lng >= 0:
                self.game_over, self.reason = True, f"{s_i} snake crashed into a boundary."
                return
            if head_is in snake.elements[1:]:
                self.game_over, self.reason = True, f"{s_i} snake crashed into itself."
                return
            for o_i in range(s_i+1, len(self.snakes)-1):
                if head_is in self.snakes[o_i].elements[1:]:
                    self.game_over, self.reason = True, f"{s_i} snake and {o_i} snake crashed."  # attribution multiplayer
                return

        # check if food
        for s_i in range(len(self.snakes)):
            head_is = self.snakes[s_i].elements[0]
            for f_i in range(len(self.foods)):
                if head_is == self.foods[f_i].at:
                    self.snakes[s_i].growing += self.foods[f_i].value
                    self.snakes[s_i].score += self.foods[f_i].value
                    self.foods[f_i] = Food()


class Square(pygame.sprite.Sprite):

    def __init__(self, length=BLOCK_SIZE, fill=LIGHT_BLUE):
        super().__init__()

        self.image = pygame.Surface((length, length))
        self.image.fill(fill)
        # self.image = pygame.image.load(copy.deepcopy(obj))
        self.rect = self.image.get_rect()


pygame.init()
game = Game()
game.loop()
print(game.reason)

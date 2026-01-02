import pygame
import random
import time
import math
from collections import deque
from pygame.math import Vector2

# --- CONFIGURATION & CONSTANTS ---
SCREEN_W, SCREEN_H = 1280, 720
WORLD_W, WORLD_H = 2000, 2000  # The universe is larger than the screen
FPS = 60
CELL_SIZE = 120

# Lotka-Volterra Tuning
PREY_START = 100
PREDATOR_START = 8
FOOD_RATE = 0.3          # Chance of food spawning per frame
PREY_METABOLISM = 0.5    # Energy lost per frame
PRED_METABOLISM = 0.8    # Predators burn energy faster
REPRO_COST_PREY = 100
REPRO_COST_PRED = 250

# Colors (Neon Palette)
C_BG = (8, 8, 14)
C_GRID = (20, 25, 40)
C_CYAN = (0, 255, 240)      # Prey
C_RED = (255, 40, 80)       # Predator
C_GREEN = (100, 255, 120)   # Food
C_WHITE = (220, 220, 220)
C_HUD_BG = (15, 15, 20, 200)

# --- ENGINE UTILITIES ---

class Camera:
    def __init__(self, width, height):
        self.camera = pygame.Rect(0, 0, width, height)
        self.width = width
        self.height = height
        self.zoom_level = 1.0
        self.target_zoom = 1.0
        self.offset = Vector2(0, 0)
        self.overview_mode = False

    def toggle_overview(self):
        self.overview_mode = not self.overview_mode
        if self.overview_mode:
            # Zoom out to fit world width
            scale_x = SCREEN_W / WORLD_W
            scale_y = SCREEN_H / WORLD_H
            self.target_zoom = min(scale_x, scale_y) * 0.9
        else:
            self.target_zoom = 1.0

    def update(self):
        # Smooth Zoom Lerp
        self.zoom_level += (self.target_zoom - self.zoom_level) * 0.1
        
        # Center camera on world center if in overview, else center on player (or specific point)
        if self.overview_mode:
            target_x = (WORLD_W * self.zoom_level - SCREEN_W) / 2
            target_y = (WORLD_H * self.zoom_level - SCREEN_H) / 2
            self.offset.x = -target_x
            self.offset.y = -target_y
        else:
            # Simple centering for now, can follow an agent later
            self.offset.x = -(WORLD_W * self.zoom_level - SCREEN_W) / 2
            self.offset.y = -(WORLD_H * self.zoom_level - SCREEN_H) / 2

    def apply(self, pos):
        """Convert World Pos -> Screen Pos"""
        return (pos * self.zoom_level) + self.offset

    def unapply(self, screen_pos):
        """Convert Screen Pos -> World Pos (for mouse clicks)"""
        return (Vector2(screen_pos) - self.offset) / self.zoom_level

class SpatialGrid:
    def __init__(self):
        self.cells = {}
    
    def clear(self):
        self.cells = {}

    def add(self, obj):
        idx = (int(obj.pos.x // CELL_SIZE), int(obj.pos.y // CELL_SIZE))
        if idx not in self.cells: self.cells[idx] = []
        self.cells[idx].append(obj)

    def get_nearby(self, pos, r=1):
        found = []
        cx, cy = int(pos.x // CELL_SIZE), int(pos.y // CELL_SIZE)
        for x in range(cx - r, cx + r + 1):
            for y in range(cy - r, cy + r + 1):
                if (x, y) in self.cells:
                    found.extend(self.cells[(x, y)])
        return found

# --- ENTITIES ---

class Entity:
    def __init__(self, x, y):
        self.pos = Vector2(x, y)
        self.active = True

class Food(Entity):
    def draw(self, surface, camera):
        screen_pos = camera.apply(self.pos)
        size = 3 * camera.zoom_level
        pygame.draw.circle(surface, C_GREEN, (int(screen_pos.x), int(screen_pos.y)), int(max(1, size)))

class Agent(Entity):
    def __init__(self, x, y, dna):
        super().__init__(x, y)
        self.vel = Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
        self.acc = Vector2(0, 0)
        self.dna = dna # speed, force, sense
        self.energy = 150
        self.max_energy = 400
        self.radius = 5
        self.color = C_WHITE
        self.wander_theta = random.uniform(0, 100)

    def edges(self):
        # Toroidal wrap (Pacman style)
        if self.pos.x > WORLD_W: self.pos.x = 0
        if self.pos.x < 0: self.pos.x = WORLD_W
        if self.pos.y > WORLD_H: self.pos.y = 0
        if self.pos.y < 0: self.pos.y = WORLD_H

    def update_physics(self):
        self.vel += self.acc
        if self.vel.length() > self.dna['speed']:
            self.vel.scale_to_length(self.dna['speed'])
        self.pos += self.vel
        self.acc *= 0
        self.edges()

    def steer(self, target, mult=1.0):
        desired = target - self.pos
        if desired.length() == 0: return Vector2(0,0)
        desired.scale_to_length(self.dna['speed'])
        steer = desired - self.vel
        if steer.length() > self.dna['force']: steer.scale_to_length(self.dna['force'])
        return steer * mult

    def draw(self, surface, camera):
        sp = camera.apply(self.pos)
        r = self.radius * camera.zoom_level
        
        # Glow
        s = pygame.Surface((int(r*4), int(r*4)), pygame.SRCALPHA)
        pygame.draw.circle(s, (*self.color, 50), (int(r*2), int(r*2)), int(r*1.5))
        surface.blit(s, (sp.x - r*2, sp.y - r*2))
        
        # Core
        pygame.draw.circle(surface, self.color, (int(sp.x), int(sp.y)), int(max(1, r)))

class Prey(Agent):
    def __init__(self, x, y, dna=None):
        dna = dna if dna else {'speed': 3.5, 'force': 0.5, 'sense': 100}
        super().__init__(x, y, dna)
        self.color = C_CYAN
        self.radius = 5

    def update(self, grid_food, grid_pred):
        # Lotka-Volterra: Energy Decay
        self.energy -= PREY_METABOLISM + (self.vel.length_squared() * 0.01)

        neighbors_pred = grid_pred.get_nearby(self.pos)
        neighbors_food = grid_food.get_nearby(self.pos)
        
        closest_pred = None
        min_p_dist = self.dna['sense']
        for p in neighbors_pred:
            d = self.pos.distance_to(p.pos)
            if d < min_p_dist:
                min_p_dist = d
                closest_pred = p

        force = Vector2(0,0)

        # 1. Flee Predator (High Priority)
        if closest_pred:
            force += self.steer(closest_pred.pos, -5.0)

        # 2. Eat Food (If safe)
        elif self.energy < self.max_energy:
            closest_food = None
            min_f_dist = self.dna['sense']
            for f in neighbors_food:
                if not f.active: continue
                d = self.pos.distance_to(f.pos)
                if d < min_f_dist:
                    min_f_dist = d
                    closest_food = f
            
            if closest_food:
                force += self.steer(closest_food.pos, 1.5)
                if min_f_dist < 10:
                    self.energy += 50
                    closest_food.active = False

        # 3. Wander
        if force.length() < 0.1:
            # Perlin-ish wander
            self.wander_theta += random.uniform(-0.3, 0.3)
            circle = self.vel.normalize() * 30 if self.vel.length() > 0 else Vector2(1,0)
            offset = Vector2(10, 0).rotate_rad(self.wander_theta)
            force += self.steer(self.pos + circle + offset, 0.5)

        self.acc += force
        self.update_physics()

class Predator(Agent):
    def __init__(self, x, y, dna=None):
        dna = dna if dna else {'speed': 4.2, 'force': 0.3, 'sense': 180}
        super().__init__(x, y, dna)
        self.color = C_RED
        self.radius = 8
        self.energy = 300

    def update(self, grid_prey):
        # Lotka-Volterra: Higher Decay for Predators
        self.energy -= PRED_METABOLISM + (self.vel.length_squared() * 0.01)

        neighbors = grid_prey.get_nearby(self.pos, r=2)
        closest = None
        min_dist = self.dna['sense']

        for p in neighbors:
            if not p.active: continue
            d = self.pos.distance_to(p.pos)
            if d < min_dist:
                min_dist = d
                closest = p
        
        force = Vector2(0,0)
        
        if closest:
            force += self.steer(closest.pos, 1.2)
            if min_dist < 12: # Catch radius
                self.energy += 120 # Energy gain from eating
                closest.active = False
        else:
            # Efficient patrolling
            self.wander_theta += random.uniform(-0.1, 0.1)
            force += Vector2(1, 0).rotate_rad(self.wander_theta) * 0.5

        self.acc += force
        self.update_physics()

# --- MAIN APPLICATION ---

class SimulationApp:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.HWSURFACE | pygame.DOUBLEBUF)
        pygame.display.set_caption("BioSim: Lotka-Volterra Universe")
        self.clock = pygame.time.Clock()
        
        self.font_lg = pygame.font.SysFont("Arial Black", 50)
        self.font_md = pygame.font.SysFont("Consolas", 20)
        self.font_sm = pygame.font.SysFont("Consolas", 14)
        
        self.camera = Camera(SCREEN_W, SCREEN_H)
        self.running = True
        self.state = "INTRO" # INTRO, SIM, GAMEOVER

    def reset_sim(self):
        self.food = [Food(random.randint(0, WORLD_W), random.randint(0, WORLD_H)) for _ in range(400)]
        self.prey = [Prey(random.randint(0, WORLD_W), random.randint(0, WORLD_H)) for _ in range(PREY_START)]
        self.preds = [Predator(random.randint(0, WORLD_W), random.randint(0, WORLD_H)) for _ in range(PREDATOR_START)]
        
        self.grid_food = SpatialGrid()
        self.grid_prey = SpatialGrid()
        self.grid_preds = SpatialGrid()
        
        self.stats_history_prey = deque(maxlen=200)
        self.stats_history_pred = deque(maxlen=200)
        self.start_time = time.time()
        
        # Track max stats
        self.max_prey = 0
        self.max_pred = 0

    # --- SCREENS ---

    def draw_text_centered(self, text, font, col, y_off=0):
        s = font.render(text, True, col)
        r = s.get_rect(center=(SCREEN_W//2, SCREEN_H//2 + y_off))
        self.screen.blit(s, r)

    def screen_intro(self):
        self.screen.fill(C_BG)
        self.draw_text_centered("BIOSIM: NEON GENESIS", self.font_lg, C_CYAN, -80)
        self.draw_text_centered("Lotka-Volterra Evolutionary Engine", self.font_md, C_WHITE, -20)
        
        instructions = [
            "Observe the delicate balance of nature.",
            "",
            "[ RIGHT CLICK ] Toggle Universe View (God Mode)",
            "[ LEFT CLICK ]  Spawn Predator at cursor",
            "",
            "Press [SPACE] to Begin Initialization"
        ]
        
        for i, line in enumerate(instructions):
            col = C_GREEN if "SPACE" in line else C_WHITE
            self.draw_text_centered(line, self.font_sm, col, 60 + i*25)

        pygame.display.flip()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT: self.running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                self.reset_sim()
                self.state = "SIM"

    def screen_gameover(self):
        # Draw transparent overlay
        s = pygame.Surface((SCREEN_W, SCREEN_H))
        s.set_alpha(10)
        s.fill((0,0,0))
        self.screen.blit(s, (0,0))
        
        duration = int(time.time() - self.start_time)
        
        self.draw_text_centered("ECOSYSTEM COLLAPSE", self.font_lg, C_RED, -100)
        
        stats = [
            f"Simulation Duration: {duration} seconds",
            f"Peak Prey Population: {self.max_prey}",
            f"Peak Predator Population: {self.max_pred}",
            "",
            "Reason: Extinction event detected.",
            "",
            "[SPACE] Restart Simulation",
            "[ESC] Quit to Desktop"
        ]
        
        for i, line in enumerate(stats):
            self.draw_text_centered(line, self.font_md, C_WHITE, -20 + i*30)
            
        pygame.display.flip()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT: self.running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE: self.running = False
                if event.key == pygame.K_SPACE: 
                    self.reset_sim()
                    self.state = "SIM"

    # --- SIMULATION LOOP ---

    def run_sim_logic(self):
        # 1. Inputs
        for event in pygame.event.get():
            if event.type == pygame.QUIT: self.running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: self.state = "GAMEOVER"
            
            # --- MOUSE INTERACTIONS ---
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 3: # Right Click
                    self.camera.toggle_overview()
                if event.button == 1: # Left Click
                    mx, my = pygame.mouse.get_pos()
                    world_pos = self.camera.unapply((mx, my))
                    self.preds.append(Predator(world_pos.x, world_pos.y))

        self.camera.update()

        # 2. Rebuild Spatial Grids
        self.grid_food.clear(); self.grid_prey.clear(); self.grid_preds.clear()
        
        # 3. Entity Management (Death & Garbage Collection)
        self.food = [f for f in self.food if f.active]
        self.prey = [p for p in self.prey if p.active and p.energy > 0]
        self.preds = [p for p in self.preds if p.active and p.energy > 0]
        
        # Check Fail State
        if len(self.prey) == 0 and len(self.preds) == 0:
            self.state = "GAMEOVER"
            return

        # Register to Grids
        for f in self.food: self.grid_food.add(f)
        for p in self.prey: self.grid_prey.add(p)
        for p in self.preds: self.grid_preds.add(p)

        # 4. Updates & Evolution
        
        # Food Regrowth
        if len(self.food) < 800 and random.random() < FOOD_RATE:
            self.food.append(Food(random.randint(0, WORLD_W), random.randint(0, WORLD_H)))

        # Prey Logic
        new_prey = []
        for p in self.prey:
            p.update(self.grid_food, self.grid_preds)
            # Reproduction
            if p.energy > REPRO_COST_PREY + 50:
                p.energy -= REPRO_COST_PREY
                # Mutation
                new_dna = {k: v * random.uniform(0.9, 1.1) for k,v in p.dna.items()}
                new_prey.append(Prey(p.pos.x, p.pos.y, new_dna))
        self.prey.extend(new_prey)

        # Predator Logic
        new_preds = []
        for p in self.preds:
            p.update(self.grid_prey)
            # Reproduction (Requires more energy)
            if p.energy > REPRO_COST_PRED + 50:
                p.energy -= REPRO_COST_PRED
                new_dna = {k: v * random.uniform(0.9, 1.1) for k,v in p.dna.items()}
                new_preds.append(Predator(p.pos.x, p.pos.y, new_dna))
        self.preds.extend(new_preds)

        # Stats Update
        self.max_prey = max(self.max_prey, len(self.prey))
        self.max_pred = max(self.max_pred, len(self.preds))
        if pygame.time.get_ticks() % 10 == 0:
            self.stats_history_prey.append(len(self.prey))
            self.stats_history_pred.append(len(self.preds))

    def draw_sim(self):
        self.screen.fill(C_BG)
        
        # Draw World Boundaries if in God Mode
        if self.camera.overview_mode:
            tl = self.camera.apply(Vector2(0,0))
            br = self.camera.apply(Vector2(WORLD_W, WORLD_H))
            pygame.draw.rect(self.screen, C_GRID, (tl.x, tl.y, br.x-tl.x, br.y-tl.y), 2)
        
        # Draw Entities
        for f in self.food: f.draw(self.screen, self.camera)
        for p in self.prey: p.draw(self.screen, self.camera)
        for p in self.preds: p.draw(self.screen, self.camera)
        
        # Draw HUD
        self.draw_hud()
        
        pygame.display.flip()

    def draw_hud(self):
        # Panel
        h = 150
        s = pygame.Surface((300, h), pygame.SRCALPHA)
        s.fill(C_HUD_BG)
        self.screen.blit(s, (10, 10))
        
        # Text
        lines = [
            f"PREY: {len(self.prey)}",
            f"PREDATORS: {len(self.preds)}",
            f"FPS: {int(self.clock.get_fps())}"
        ]
        for i, l in enumerate(lines):
            c = C_CYAN if "PREY" in l else C_RED if "PRED" in l else C_WHITE
            self.screen.blit(self.font_sm.render(l, True, c), (20, 20 + i*18))
            
        # Graph (Lotka-Volterra Visualizer)
        graph_rect = pygame.Rect(20, 80, 260, 60)
        pygame.draw.rect(self.screen, (30, 30, 40), graph_rect)
        
        if len(self.stats_history_prey) > 2:
            max_val = max(max(self.stats_history_prey), max(self.stats_history_pred), 1)
            
            def get_pts(data, color):
                pts = []
                for x, val in enumerate(data):
                    px = 20 + (x / 200) * 260
                    py = 140 - (val / max_val) * 60
                    pts.append((px, py))
                if len(pts) > 1: pygame.draw.lines(self.screen, color, False, pts, 2)
            
            get_pts(self.stats_history_prey, C_CYAN)
            get_pts(self.stats_history_pred, C_RED)

        # Mode Indicator
        mode_txt = "VIEW: GOD MODE" if self.camera.overview_mode else "VIEW: FOCUSED"
        self.screen.blit(self.font_sm.render(mode_txt, True, C_GREEN), (20, 155))

    # --- MAIN LOOP ---
    
    def run(self):
        while self.running:
            if self.state == "INTRO":
                self.screen_intro()
            elif self.state == "SIM":
                self.run_sim_logic()
                self.draw_sim()
            elif self.state == "GAMEOVER":
                self.screen_gameover()
            self.clock.tick(FPS)
        pygame.quit()

if __name__ == "__main__":
    app = SimulationApp()
    app.run()
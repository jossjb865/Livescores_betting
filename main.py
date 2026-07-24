import os
import requests
from datetime import datetime

# Credenciales inyectadas desde GitHub Secrets
ODDS_API_KEY = os.environ.get('ODDS_API_KEY')
ISPORTS_API_KEY = os.environ.get('ISPORTS_API_KEY')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# Endpoints oficiales
ODDS_URL = "https://api.the-odds-api.com/v4/sports/soccer/odds/"
ISPORTS_STATS_URL = "http://api.isportsapi.com/sport/football/team/recent" 
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

def get_live_odds():
    params = {
        'apiKey': ODDS_API_KEY,
        'regions': 'eu,us,uk',
        'markets': 'h2h',
        'oddsFormat': 'decimal'
    }
    response = requests.get(ODDS_URL, params=params)
    response.raise_for_status()
    return response.json()

def get_team_stats(team_name):
    params = {
        'api_key': ISPORTS_API_KEY,
        'team_name': team_name, 
        'limit': 5
    }
    response = requests.get(ISPORTS_STATS_URL, params=params)
    if response.status_code == 200:
        return response.json().get('data', [])
    return []

def calculate_true_probability(stats):
    # Si no hay datos (0 juegos), devolvemos 0 para evitar falsos positivos
    if not stats:
        return 0.0 
    
    points = 0
    total_games = len(stats)
    goal_difference = 0
    
    for game in stats:
        if game.get('result') == 'W':
            points += 3
        elif game.get('result') == 'D':
            points += 1
            
        home_score = game.get('home_score', 0)
        away_score = game.get('away_score', 0)
        
        if game.get('is_home'):
            goal_difference += (home_score - away_score)
        else:
            goal_difference += (away_score - home_score)
        
    win_rate = points / (total_games * 3)
    performance_modifier = goal_difference * 0.02
    
    true_prob = min(max(win_rate + performance_modifier, 0.05), 0.95)
    return true_prob

def send_telegram_alert(message):
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    requests.post(TELEGRAM_URL, json=payload)

def main():
    print(f"[{datetime.now()}] Iniciando escaneo de mercados en vivo...")
    odds_data = get_live_odds()
    
    apuestas_encontradas = [] # Lista para almacenar las oportunidades
    
    for match in odds_data:
        home_team = match['home_team']
        away_team = match['away_team']
        
        for bookmaker in match['bookmakers']:
            for market in bookmaker['markets']:
                if market['key'] == 'h2h':
                    for outcome in market['outcomes']:
                        team = outcome['name']
                        odds = outcome['price']
                        
                        implied_prob = 1 / odds 
                        team_stats = get_team_stats(team)
                        true_prob = calculate_true_probability(team_stats)
                        
                        edge = true_prob - implied_prob
                        
                        # Solo consideramos edge si tenemos datos del equipo (>0)
                        if edge > 0.05 and len(team_stats) > 0: 
                            wins = sum(1 for g in team_stats if g.get('result') == 'W')
                            draws = sum(1 for g in team_stats if g.get('result') == 'D')
                            losses = sum(1 for g in team_stats if g.get('result') == 'L')
                            
                            mensaje = (
                                f"🚨 *APUESTA DE VALOR ENCONTRADA* 🚨\n\n"
                                f"⚽ *Partido:* {home_team} vs {away_team}\n"
                                f"📈 *Selección:* {team}\n"
                                f"🏦 *Casa:* {bookmaker['title']}\n"
                                f"💰 *Cuota:* {odds} (Implícita: {implied_prob*100:.1f}%)\n"
                                f"📊 *Probabilidad Real:* {true_prob*100:.1f}%\n"
                                f"🔥 *Edge:* {edge*100:.1f}%\n\n"
                                f"📌 *Trayectoria (Últimos {len(team_stats)} juegos):*\n"
                                f"Récord: {wins}G - {draws}E - {losses}P\n"
                            )
                            
                            # Guardamos la apuesta en la lista
                            apuestas_encontradas.append({
                                'mensaje': mensaje,
                                'edge': edge
                            })

    # Ordenamos la lista de mayor a menor edge
    apuestas_encontradas.sort(key=lambda x: x['edge'], reverse=True)
    
    # Extraemos solo las 5 mejores
    top_5 = apuestas_encontradas[:5]
    
    # Enviamos el Top 5 a Telegram
    for apuesta in top_5:
        send_telegram_alert(apuesta['mensaje'])
        
    print(f"Escaneo finalizado. Se enviaron {len(top_5)} alertas de {len(apuestas_encontradas)} encontradas.")

if __name__ == "__main__":
    main()

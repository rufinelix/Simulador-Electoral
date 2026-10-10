# 🗳️ Simulador Electoral D'Hondt y Laboratorio de Coaliciones (España)

Un simulador y analizador electoral avanzado en Python basado en la **Ley D'Hondt** y la legislación electoral española (**LOREG**, Ley Orgánica del Régimen Electoral General, art. 163).

El sistema reproduce el reparto de los **350 escaños del Congreso de los Diputados** a lo largo de las **52 circunscripciones** (50 provincias + Ceuta y Melilla), proporciona **gráficas escalonadas interactivas** con Plotly, conecta con sondeos y encuestas electorales (CIS, 40dB, ElectoPanel, GAD3, APIs JSON), y responde a la pregunta politológica clave:

> **¿Compensa una lista única de izquierdas (Sumar + Podemos) frente a ir por separado cuando existe fricción/desafección de votantes? ¿Cuántos votos necesitaría el bloque para igualar los escaños del escenario más favorable?**

---

## 🚀 Arquitectura y Secciones de la Aplicación

La aplicación se estructura en **cuatro secciones especializadas**, situando cada parámetro de control directamente en la pestaña donde surte efecto (sin paneles globales invasivos):

### 1. 🇪🇸 Simulación Nacional Simple
- **Proyección Macro:** Carga de encuestas (CIS, 40dB, ElectoPanel, GAD3, 23J) con proyección territorial mediante *Ratio Swing* sobre las 52 circunscripciones.
- **Laboratorio Dual de Izquierdas:** Comparativa directa del bloque de izquierdas (Sumar + Podemos) acudiendo en lista única o por separado.
- **Modelado de Desafección:** Regulación del porcentaje de retención/fuga global de la coalición ($V_{\text{coal}} = R \times \sum V_i$).
- **Optimización Inversa:** Responde matemáticamente a la pregunta clave: *¿Cuántos votos adicionales ($\Delta V$) y porcentaje ($\Delta\%$) necesitaría el bloque dividido para igualar los escaños de la coalición más favorable?*
- **Gráfica Escalonada Descendente interactiva:** Visualiza el reparto como una carrera por los escaños ($Y = \text{cociente/votos}$, $X = \text{escaños}$) con línea de corte del último escaño.
- **🗺️ Mapa Electoral Interactivo de España:** Coropletas con Canarias en recuadro oficial (inset), alternancia de capas (Fuerza Ganadora, Impacto Territorial de la Coalición, % de Voto, Escaños en juego) y fichas de auditoría local.

### 2. 🎯 Simulación Compleja de una Sola Circunscripción
- **Entorno de Simulación Aislada:** Permite analizar a fondo una circunscripción real (cargada del 23J o sondeos) o crear una provincia libre desde cero.
- **Modo de Entrada Flexible:** Selección entre introducción por **Votos Absolutos** o **Porcentajes de Voto**.
- **Parámetros Electorales Exhaustivos:** Control total sobre censo electoral, participación (%), votos nulos, votos en blanco (%) y umbral legal de exclusión (3% LOREG sobre votos válidos).
- **Fuga de Votos Individualizada Partido a Partido:** Tasa de transferencia específica $R_p \in [0\%, 120\%]$ para cada fuerza política de la coalición:
  $$V_{\text{coal}} = \sum_{p \in C} R_p \cdot V_p$$
- **Añadir Candidatura:** Inserción dinámica de cualquier fuerza política adicional (nacional, regional o local).
- **Optimizador Inverso Local:** Búsqueda binaria de los votos exactos que necesitaría el bloque fragmentado para obtener el mismo resultado que la coalición en esa circunscripción.
- **Gráficas Escalonadas Paralelas:** Visualización simultánea del escenario de partidos separados frente al escenario en coalición.
- **🗺️ Mapa de Contexto Geográfico:** Visualiza la provincia seleccionada en el mapa de España resaltando su ubicación y peso en el Congreso.

### 3. 🗺️ Simulación Nacional Compleja (Control Circunscripción a Circunscripción)
- **Preconfiguración General:** Define una coalición base (ej. Sumar + Podemos) y tasas de retención por partido aplicadas de inicio a las 52 provincias.
- **Personalización Granular Provincia a Provincia:** 
  - Selección libre de qué candidaturas se integran en la coalición en cada circunscripción concreta (pudiendo tener coaliciones asimétricas según el territorio).
  - Presencia explícita de **Adelante Andalucía** en las 8 circunscripciones andaluzas (Almería, Cádiz, Córdoba, Granada, Huelva, Jaén, Málaga, Sevilla).
  - Botón **"Añadir candidatura"** para incorporar fuerzas no previstas en el mapa inicial.
  - Ajuste de censo, participación, votos nulos, blancos y edición directa de votos o porcentajes.
- **Selector de Recuento Nacional:**
  - *Todos los partidos por separado.*
  - *Con las coaliciones y ajustes definidos circunscripción a circunscripción.*
- **🗺️ Mapa Territorial Completo de España:** Refleja en tiempo real las transferencias de escaños y el resultado de las 52 provincias con ajustes personalizados aplicados.
- **Escrutinio Agregado y Auditoría Territorial:** Desglose del Congreso de 350 diputados, tabla comparativa de mayorías parlamentarias y visor detallado provincia a provincia.

### 4. 📋 Auditoría, Metodología e Ingesta de Excel
- **Ingesta de Encuestas y Datos Propios:** Permite subir archivos `.xlsx`, `.xls` o `.csv` con sondeos propios o microdatos electorales.
- **Generador de Plantillas:** Botón de descarga interactivo que genera una plantilla Excel (`.xlsx`) en memoria con la estructura exacta requerida:
  - Formato por Circunscripción (52 filas con censo, participación y porcentajes/votos por partido).
  - Formato Nacional Simplificado (partido y porcentaje nacional).
- **Auditoría Metodológica:** Explicación formal de la Ley D'Hondt, formulación de cocientes, cálculo del umbral LOREG (Art. 163) y algoritmo de bisección para optimización inversa.
- **Fuentes Oficiales:** Referencias al BOE (Real Decreto 400/2023), datos censales del INE y sondeos del CIS.

---

## 📂 Estructura del Proyecto

```text
simulador_electoral_dhondt/
├── app.py                     # Aplicación web interactiva en Streamlit (4 secciones)
├── main.py                    # Lanzador principal y modo CLI
├── core/
│   ├── dhondt.py              # Algoritmo puro D'Hondt, umbrales LOREG y cocientes de corte
│   ├── stepped_chart.py       # Gráfica escalonada descendente en Plotly (X=escaños, Y=cociente)
│   ├── electoral_map.py       # Mapa cartográfico interactivo de España (Plotly/GeoJSON, coropletas y capas)
│   ├── toponyms.py            # Normalizador toponímico integral (castellano / cooficial / BOE / INE)
│   └── national_model.py      # Agregador de 52 circunscripciones, Swing y coaliciones asimétricas
├── data/
│   ├── circunscripciones_2023.json  # Base de datos oficial 23J (52 provincias, con Adelante Andalucía)
│   ├── spain_provinces.geojson      # GeoJSON con los límites de las 52 circunscripciones
│   ├── spain_provinces_inset.geojson# GeoJSON con Canarias en recuadro oficial (inset)
│   ├── poll_connector.py      # Conector de sondeos (CIS, 40dB, ElectoPanel, GAD3, API JSON)
│   └── polls_cache.json       # Caché local de sondeos
├── analysis/
│   ├── coalition_analyzer.py      # Comparador dual, optimizador inverso y fuga partido a partido
│   └── government_optimizer.py    # Optimizador de Gobernabilidad (176 escaños), búsqueda binaria y criterios multicriterio
├── tests/
│   ├── test_dhondt.py             # Tests unitarios del motor D'Hondt y modelo nacional
│   ├── test_analysis.py           # Test de optimización inversa y breakeven
│   ├── test_government_optimizer.py# Tests del motor de investidura, criterios multicriterio y blindaje
│   ├── test_electoral_map.py      # Tests unitarios del mapa interactivo y capas cartográficas
│   ├── test_cross_modules.py      # Test de integración cruzada E2E y resolución toponímica
│   └── test_ui_state_sync.py      # Tests de reactividad y purga de estado en interfaz Streamlit
└── README.md                      # Documentación del proyecto
```

---

## ⚙️ Instalación y Requisitos

El proyecto utiliza librerías estándar de Python para ciencia de datos y visualización:

```bash
pip install streamlit plotly pandas numpy requests openpyxl
```

---

## 🖥️ Uso del Programa

### 1. Iniciar la Aplicación Web Interactiva (Streamlit)
Desde la terminal en el directorio del proyecto:

```bash
streamlit run simulador_electoral_dhondt/app.py
```
o mediante el script de inicio:
```bash
python simulador_electoral_dhondt/main.py --app
```

### 2. Ejecutar Análisis por Línea de Comandos (CLI)
Para obtener el cálculo de coalición directamente en la consola con un 85% de retención:

```bash
python simulador_electoral_dhondt/main.py --cli --retention 85
```

---

## 🧠 Metodología Matemática y Modelado Electoral

### 1. ¿Por qué la gráfica escalonada tiene $X$ dependiente de $Y$?
En el sistema D'Hondt, los cocientes son $Q_k = V / k$. Fijando un valor de corte $Y$ en votos/cociente, el número de escaños de un partido viene dado por:
$$X(Y) = \left\lfloor \frac{V}{Y} \right\rfloor$$
Al graficar los votos/cociente en el **eje vertical Y** y los escaños en el **eje horizontal X**:
- Para valores de $Y > V$, el partido tiene $0$ escaños.
- Al descender $Y$ hasta $V/1$, el partido consigue su $1^{\text{er}}$ escaño.
- Al descender hasta $V/2$, salta al $2^{\text{do}}$ escaño.
- La línea roja horizontal marca el **cociente de corte del último escaño asignado ($S$)**. Todos los peldaños que toquen o superen esa línea obtienen representación, representando el cálculo como una carrera visual descendente.

### 2. Formulación de Fuga de Votos Partido a Partido
En una coalición integrada por el conjunto de partidos $C = \{p_1, p_2, \dots, p_k\}$, cada partido $p$ tiene una tasa de retención $R_p \in [0, 1.2]$ (donde $1.0$ representa fidelidad total, $<1.0$ rechazo/abstención, y $>1.0$ efecto movilizador):
$$V_{\text{coalición}} = \sum_{p \in C} R_p \cdot V_p$$
Los votos que no se transfieren $((1 - R_p) \cdot V_p)$ corresponden a abstención o voto nulo/blanco motivado por desafección.

### 3. Optimizador Inverso mediante Búsqueda Binaria
Para responder a la pregunta de cuántos votos adicionales $\Delta V$ necesita el bloque fragmentado para empatar los escaños de la lista única:
1. Calculamos los escaños del escenario coaligado $S_{\text{coal}}$.
2. Si $S_{\text{sep}} \ge S_{\text{coal}}$, $\Delta V = 0$.
3. Si $S_{\text{sep}} < S_{\text{coal}}$, aplicamos bisección sobre el intervalo de votos adicionales $[0, V_{\text{max}}]$ distribuidos proporcionalmente entre los partidos separados hasta hallar el valor mínimo $\Delta V^*$ tal que:
$$S_{\text{sep}}(V + \Delta V^*) = S_{\text{coal}}$$

### 4. Optimizador de Gobernabilidad e Investidura (176 Escaños)
Calcula el camino óptimo hacia la mayoría parlamentaria absoluta mediante búsqueda binaria iterativa en cada circunscripción, seleccionando en cada paso el escaño marginalmente más eficiente según cuatro criterios rigurosos:
1. **Puntos % Provinciales ($\Delta\%_{\text{prov}}$):** Minimiza el esfuerzo de persuasión sociológico en el electorado local ($\Delta V_c / \text{Válidos}_c$).
2. **Crecimiento Orgánico del Partido ($\Delta\%_{\text{partido}}$):** Minimiza la sobreexigencia orgánica a la propia candidatura ($\Delta V_c / V_{\text{partido}, c}$).
3. **Híbrido Ponderado (Media Geométrica Cobb-Douglas):** Equilibra ambas dimensiones con parámetro $\alpha \in [0, 1]$:
   $$\text{Coste} = \left(\Delta\%_{\text{prov}}\right)^{1 - \alpha} \cdot \left(\Delta\%_{\text{partido}}\right)^{\alpha}$$
4. **Votos Brutos Absolutos ($\Delta V$):** Minimiza el volumen total de papeletas netas adicionales.

Incluye además **blindaje estricto de socios** (evita canibalización del bloque de investidura), **cota física del censo electoral**, **tope máximo de crecimiento local** y modelado de **porosidad partido a partido**.


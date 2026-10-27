# -*- coding: utf-8 -*-
"""Grafemas -> fonemas -> visemas para espanol.
El espanol se escribe casi como suena, asi que bastan reglas: no hace falta
diccionario ni modelo."""

VOCALES = set('aeiou')
_TILDES = str.maketrans('áéíóúàèìòù', 'aeiouaeiou')
# la x de estos topónimos suena como j, no como ks
_X_JOTA = ('mexic', 'oaxac', 'texa', 'xavier', 'ximena', 'xime')

def fonemas(palabra):
    w = palabra.lower().translate(_TILDES)
    w = ''.join(c for c in w if c.isalpha() or c in 'ñü')
    x_es_jota = any(w.startswith(p) for p in _X_JOTA)
    out, i, n = [], 0, len(w)
    while i < n:
        c = w[i]
        nx = w[i+1] if i+1 < n else ''
        nx2 = w[i+2] if i+2 < n else ''
        if c == 'c' and nx == 'h':
            out.append('tS'); i += 2
        elif c == 'l' and nx == 'l':
            out.append('Y'); i += 2
        elif c == 'r' and nx == 'r':
            out.append('r'); i += 2
        elif c == 'q' and nx == 'u':
            out.append('k'); i += 2 if nx2 in 'ei' else 1
        elif c == 'g' and nx == 'ü':
            out.extend(['g', 'u']); i += 2          # la dieresis hace sonar la u
        elif c == 'g' and nx == 'u' and nx2 in 'ei':
            out.append('g'); i += 2
        elif c == 'c':
            out.append('s' if nx in 'ei' else 'k'); i += 1
        elif c == 'g':
            out.append('x' if nx in 'ei' else 'g'); i += 1
        elif c == 'z':
            out.append('s'); i += 1
        elif c == 'j':
            out.append('x'); i += 1
        elif c == 'h':
            i += 1                                   # muda
        elif c == 'v':
            out.append('b'); i += 1
        elif c == 'w':
            out.append('u'); i += 1
        elif c == 'x':
            out.append('x') if x_es_jota else out.extend(['k', 's'])
            i += 1
        elif c == 'ü':
            out.append('u'); i += 1
        elif c == 'ñ':
            out.append('N'); i += 1
        elif c == 'y':
            out.append('i' if (i == n-1 or nx not in VOCALES) else 'Y'); i += 1
        else:
            out.append(c); i += 1
    return out

# visema -> (apertura px, factor de ancho, cierre de labios 0-1)
VISEMAS = {
    # El labio y la mandibula son INDEPENDIENTES: en una O real el labio baja
    # tapando parte del diente a la vez que la mandibula abre.
    'a': (17.0, 1.02, 0.00), 'e': (11.0, 1.06, 0.00), 'i': (6.0, 1.10, 0.05),
    'o': (12.0, 0.84, 0.45), 'u': (8.0,  0.76, 0.60),
    'm': (0.0, 1.00, 1.00), 'p': (0.0, 1.00, 1.00), 'b': (0.0, 1.00, 0.95),
    'f': (2.0, 1.02, 0.55),                     # labiodental
    't': (5.0, 1.00, 0.00), 'd': (5.0, 1.00, 0.00),
    'n': (5.0, 1.00, 0.00), 'l': (5.0, 1.00, 0.00),
    's': (4.0, 1.04, 0.08), 'r': (6.0, 1.00, 0.00),
    'k': (7.0, 0.98, 0.00), 'g': (7.0, 0.98, 0.00), 'x': (8.0, 0.98, 0.00),
    'tS': (5.0, 0.92, 0.30), 'Y': (5.0, 0.94, 0.15), 'N': (5.0, 0.98, 0.05),
}
# cuanto dura cada fonema respecto a los demas de la palabra
PESO = {'a':1.7,'e':1.6,'i':1.4,'o':1.6,'u':1.4,
        'm':.9,'b':.7,'p':.7,'t':.6,'d':.7,'k':.7,'g':.7,
        'f':.9,'s':1.0,'n':.8,'l':.8,'r':.7,'x':.9,
        'tS':.9,'Y':.8,'N':.8}

def objetivo(f):
    return VISEMAS.get(f, (6.0, 1.0, 0.0))

def peso(f):
    return PESO.get(f, 0.9)

if __name__ == '__main__':
    pruebas = ['que','guitarra','cigüeña','chico','llave','año','examen',
               'zapato','hola','ventana','rey','ciudad','gente','guerra',
               'México','psicólogo','quiero']
    for p in pruebas:
        print(f'{p:12s} -> {" ".join(fonemas(p))}')

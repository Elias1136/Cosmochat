import streamlit as st

def main():
    st.set_page_config(page_title="Meine App", layout="centered")
    
    st.title("Willkommen zu meiner App! 🚀")
    st.write("Dies ist eine einfache Streamlit-Anwendung, die direkt über GitHub gestartet wurde.")
    
    name = st.text_input("Wie heißt du?")
    
    if name:
        st.success(f"Hallo {name}! Schön, dass du hier bist.")
        
    st.info("Diese App wurde erfolgreich aktualisiert.")

if __name__ == "__main__":
    main()

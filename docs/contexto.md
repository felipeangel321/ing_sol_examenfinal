# Contexto del proyecto

Última actualización: 2026-11-04.

## Qué se quiere construir

Agentes de IA para corredores de seguros, que hoy no tienen este servicio.

| Para quién | Qué hacen los agentes |
|---|---|
| **Cliente** de la corredora | Un agente por tipo de seguro revisa la documentación, responde dudas antes de enviar el formulario, guía al cliente y procesa solicitudes |
| **Corredor** (quien vende seguros) | Agentes que le permiten gestionar todos estos servicios |

## Los dos productos

1. **Sitio completo para un corredor:** frontend y backend desde cero, con los agentes incluidos.
2. **Agentes para otros corredores:** el mismo servicio, instalable en las páginas que esos corredores ya tienen.

Como un mismo sistema atenderá a varios corredores, los documentos, las solicitudes y los datos de cada uno deben quedar separados desde el inicio.

## Referencia: jvsseguros.cl (solo un ejemplo)

Revisado el 2026-11-04. Solo se leyeron el inicio, contacto y las páginas de auto, incendio, vida y salud. No se revisaron "Nosotros", ingeniería, garantías ni marítimo.

- **Tipo de negocio:** corredora chilena, en Puerto Montt.
- **Seguros que ofrece:** auto, incendio (hogar y comercial), ingeniería, garantías, cascos marítimos y transporte marítimo, vida y salud.
- **Tecnología:** WordPress con Elementor y WPForms. No se vio ningún chatbot.
- **Formulario de auto:** nombre, email, tipo de auto, patente, marca, modelo, versión, año, comuna, teléfono y tipo de uso.
- **Formularios de incendio, vida, salud y contacto:** solo nombre, correo, teléfono y comentarios.
- **Documentación:** no se encontraron PDF ni condiciones de póliza, solo textos comerciales breves.

## Qué implica para el proyecto

- **Documentación:** los textos de una página así no bastan para responder sobre coberturas. Los agentes necesitarán documentos que entregue el corredor o la aseguradora.
- **Instalación en otras páginas:** como páginas así usan WordPress, la opción a evaluar es un chat que se agregue con un fragmento de código, sin rehacer el sitio.

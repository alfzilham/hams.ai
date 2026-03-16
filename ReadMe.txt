<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Teacher Portfolio</title>
    <link href="https://unpkg.com/aos@2.3.4/dist/aos.css" rel="stylesheet">
    <style>
        :root {
            --light-purple: #e6d5f7;
            --light-pink: #ffdbe6;
            --light-orange: #ffe8cc;
            --light-yellow: #fff9d9;
            --glass-bg: rgba(255, 255, 255, 0.2);
            --glass-border: rgba(255, 255, 255, 0.3);
            --shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            --transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }

        body {
            background: linear-gradient(135deg, var(--light-purple), var(--light-pink), var(--light-orange), var(--light-yellow));
            min-height: 100vh;
            overflow-x: hidden;
            position: relative;
        }

        /* Particles Animation */
        .particles {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: -1;
        }

        .particle {
            position: absolute;
            border-radius: 50%;
            background: white;
            opacity: 0.5;
            filter: blur(2px);
        }

        /* Navbar */
        .navbar {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            padding: 1rem 2rem;
            background: linear-gradient(90deg, var(--light-purple), var(--light-pink), var(--light-orange), var(--light-yellow));
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border-radius: 50px;
            box-shadow: var(--shadow);
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 1000;
            transition: var(--transition);
        }

        .navbar.sticky {
            padding: 0.75rem 2rem;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
        }

        .logo {
            font-size: 1.5rem;
            font-weight: bold;
            color: #333;
            text-decoration: none;
        }

        .nav-menu {
            display: flex;
            list-style: none;
        }

        .nav-item {
            margin-left: 1.5rem;
        }

        .nav-link {
            color: #333;
            text-decoration: none;
            font-weight: 500;
            padding: 0.5rem 1rem;
            border-radius: 20px;
            transition: var(--transition);
        }

        .nav-link:hover {
            background: rgba(255, 255, 255, 0.3);
            transform: translateY(-2px);
        }

        .hamburger {
            display: none;
            flex-direction: column;
            cursor: pointer;
        }

        .hamburger div {
            width: 25px;
            height: 3px;
            background: #333;
            margin: 3px;
            transition: var(--transition);
        }

        /* Hero Section */
        .hero {
            display: flex;
            align-items: center;
            padding: 5rem 2rem;
            min-height: 100vh;
            position: relative;
        }

        .hero-content {
            flex: 1;
            max-width: 500px;
        }

        .hero-title {
            font-size: 3.5rem;
            font-weight: 800;
            color: #333;
            line-height: 1.2;
            margin-bottom: 0.5rem;
        }

        .hero-subtitle {
            font-size: 1.2rem;
            color: #666;
            margin-bottom: 1.5rem;
        }

        .cta-buttons {
            display: flex;
            gap: 1rem;
            margin-bottom: 2rem;
        }

        .btn {
            padding: 0.75rem 1.5rem;
            border-radius: 50px;
            font-weight: 600;
            text-decoration: none;
            transition: var(--transition);
            border: none;
            cursor: pointer;
        }

        .btn-primary {
            background: linear-gradient(90deg, var(--light-purple), var(--light-pink));
            color: white;
            box-shadow: 0 4px 12px rgba(196, 142, 230, 0.4);
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(196, 142, 230, 0.6);
        }

        .btn-secondary {
            background: transparent;
            color: #333;
            border: 2px solid rgba(255, 255, 255, 0.5);
            box-shadow: 0 4px 12px rgba(255, 255, 255, 0.3);
        }

        .btn-secondary:hover {
            background: rgba(255, 255, 255, 0.2);
            transform: translateY(-2px);
        }

        .stats {
            display: flex;
            justify-content: space-between;
            margin-top: 2rem;
        }

        .stat-item {
            text-align: center;
        }

        .stat-number {
            font-size: 2rem;
            font-weight: 700;
            color: #333;
        }

        .stat-label {
            font-size: 0.9rem;
            color: #666;
        }

        .hero-cards {
            flex: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            position: relative;
        }

        .card-stack {
            position: relative;
            width: 100%;
            max-width: 400px;
        }

        .card {
            position: absolute;
            width: 250px;
            height: 300px;
            background: var(--glass-bg);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border-radius: 20px;
            box-shadow: var(--shadow);
            padding: 2rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            transition: var(--transition);
            border: 1px solid var(--glass-border);
            cursor: pointer;
        }

        .card:hover {
            transform: scale(1.05) rotate(5deg);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2);
        }

        .card:nth-child(1) {
            left: 0;
            top: 0;
            z-index: 3;
        }

        .card:nth-child(2) {
            left: 30px;
            top: 30px;
            z-index: 2;
        }

        .card:nth-child(3) {
            left: 60px;
            top: 60px;
            z-index: 1;
        }

        .card-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
        }

        .card-title {
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }

        .card-desc {
            font-size: 0.9rem;
            color: #666;
        }

        /* Highlight Effect */
        .highlight {
            position: absolute;
            top: 20%;
            right: 10%;
            width: 300px;
            height: 300px;
            background: radial-gradient(circle, rgba(255,255,255,0.3) 0%, rgba(255,255,255,0) 70%);
            border-radius: 50%;
            filter: blur(40px);
            z-index: -1;
        }

        /* Responsive Design */
        @media (max-width: 768px) {
            .navbar {
                padding: 1rem;
            }
            
            .nav-menu {
                position: fixed;
                top: 70px;
                right: -100%;
                flex-direction: column;
                background: linear-gradient(90deg, var(--light-purple), var(--light-pink), var(--light-orange), var(--light-yellow));
                width: 100%;
                text-align: center;
                transition: 0.3s;
                box-shadow: 0 10px 27px rgba(0, 0, 0, 0.05);
                padding: 2rem 0;
                border-radius: 0 0 20px 20px;
            }
            
            .nav-menu.active {
                right: 0;
            }
            
            .nav-item {
                margin: 1rem 0;
            }
            
            .hamburger {
                display: flex;
            }
            
            .hamburger.active div:nth-child(1) {
                transform: rotate(-45deg) translate(-5px, 6px);
            }
            
            .hamburger.active div:nth-child(2) {
                opacity: 0;
            }
            
            .hamburger.active div:nth-child(3) {
                transform: rotate(45deg) translate(-5px, -6px);
            }
            
            .hero {
                flex-direction: column;
                padding: 3rem 1rem;
                min-height: auto;
            }
            
            .hero-content {
                max-width: 100%;
                margin-bottom: 2rem;
            }
            
            .hero-title {
                font-size: 2.5rem;
            }
            
            .cta-buttons {
                flex-direction: column;
            }
            
            .stats {
                flex-wrap: wrap;
                gap: 1rem;
            }
            
            .hero-cards {
                width: 100%;
                justify-content: center;
            }
            
            .card-stack {
                width: 100%;
                max-width: 100%;
            }
            
            .card {
                width: 100%;
                max-width: 300px;
                position: relative;
                left: 0;
                top: 0;
                transform: none;
                margin-bottom: 1rem;
            }
            
            .card:hover {
                transform: scale(1.05);
                rotate: 0deg;
            }
        }

        @media (max-width: 480px) {
            .hero-title {
                font-size: 2rem;
            }
            
            .hero-subtitle {
                font-size: 1rem;
            }
            
            .btn {
                padding: 0.5rem 1rem;
                font-size: 0.9rem;
            }
            
            .stat-number {
                font-size: 1.5rem;
            }
        }
    </style>
</head>
<body>
    <!-- Particles Background -->
    <div class="particles" id="particles"></div>

    <!-- Floating Capsule Navbar -->
    <nav class="navbar" id="navbar">
        <a href="#" class="logo">EduGuru</a>
        <ul class="nav-menu" id="nav-menu">
            <li class="nav-item"><a href="#" class="nav-link">Home</a></li>
            <li class="nav-item"><a href="#" class="nav-link">About</a></li>
            <li class="nav-item"><a href="#" class="nav-link">Portfolio</a></li>
            <li class="nav-item"><a href="#" class="nav-link">Contact</a></li>
        </ul>
        <div class="hamburger" id="hamburger">
            <div></div>
            <div></div>
            <div></div>
        </div>
    </nav>

    <!-- Hero Section -->
    <section class="hero">
        <div class="highlight"></div>
        <div class="hero-content" data-aos="fade-right">
            <h1 class="hero-title">Hi, I'm Ms. Amelia</h1>
            <p class="hero-subtitle">Educator | Mentor | Lifelong Learner</p>
            <div class="cta-buttons">
                <a href="#" class="btn btn-primary">Get in Touch</a>
                <a href="#" class="btn btn-secondary">View Classes</a>
            </div>
            <div class="stats">
                <div class="stat-item">
                    <div class="stat-number">300+</div>
                    <div class="stat-label">Students Mentored</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number">15+</div>
                    <div class="stat-label">Years Experience</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number">99%</div>
                    <div class="stat-label">Satisfaction</div>
                </div>
            </div>
        </div>
        <div class="hero-cards" data-aos="fade-left">
            <div class="card-stack">
                <div class="card" data-aos="zoom-in" data-aos-delay="100">
                    <div class="card-icon">📚</div>
                    <h3 class="card-title">Curriculum Design</h3>
                    <p class="card-desc">Creating engaging lesson plans that inspire students to learn.</p>
                </div>
                <div class="card" data-aos="flip-left" data-aos-delay="200">
                    <div class="card-icon">💻</div>
                    <h3 class="card-title">Digital Learning</h3>
                    <p class="card-desc">Integrating technology to enhance the learning experience.</p>
                </div>
                <div class="card" data-aos="fade-up" data-aos-delay="300">
                    <div class="card-icon"> chalkboard</div>
                    <h3 class="card-title">Classroom Management</h3>
                    <p class="card-desc">Creating a positive environment for effective teaching.</p>
                </div>
            </div>
        </div>
    </section>

    <script src="https://unpkg.com/aos@2.3.4/dist/aos.js"></script>
    <script>
        // Initialize AOS
        document.addEventListener('DOMContentLoaded', function() {
            AOS.init({
                duration: 800,
                easing: 'ease-in-out',
                once: true
            });
        });

        // Navbar Scroll Effect
        window.addEventListener('scroll', function() {
            const navbar = document.getElementById('navbar');
            if (window.scrollY > 50) {
                navbar.classList.add('sticky');
            } else {
                navbar.classList.remove('sticky');
            }
        });

        // Hamburger Menu Toggle
        const hamburger = document.getElementById('hamburger');
        const navMenu = document.getElementById('nav-menu');

        hamburger.addEventListener('click', function() {
            hamburger.classList.toggle('active');
            navMenu.classList.toggle('active');
        });

        // Close menu when clicking on links
        document.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', () => {
                hamburger.classList.remove('active');
                navMenu.classList.remove('active');
            });
        });

        // Particles Animation
        function createParticles() {
            const particlesContainer = document.getElementById('particles');
            const particleCount = 50;
            
            for (let i = 0; i < particleCount; i++) {
                const particle = document.createElement('div');
                particle.classList.add('particle');
                
                // Random size between 5 and 20
                const size = Math.random() * 15 + 5;
                particle.style.width = `${size}px`;
                particle.style.height = `${size}px`;
                
                // Random position
                const posX = Math.random() * 100;
                const posY = Math.random() * 100;
                particle.style.left = `${posX}%`;
                particle.style.top = `${posY}%`;
                
                // Random animation duration
                const duration = Math.random() * 10 + 5;
                particle.style.animation = `float ${duration}s ease-in-out infinite`;
                
                particlesContainer.appendChild(particle);
            }
        }

        // Add floating animation to particles
        const styleSheet = document.createElement('style');
        styleSheet.textContent = `
            @keyframes float {
                0% { transform: translate(0px, 0px) rotate(0deg); }
                50% { transform: translate(5px, 5px) rotate(180deg); }
                100% { transform: translate(0px, 0px) rotate(360deg); }
            }
        `;
        document.head.appendChild(styleSheet);

        // Initialize particles
        createParticles();

        // Card hover effects
        const cards = document.querySelectorAll('.card');
        cards.forEach(card => {
            card.addEventListener('mouseenter', function() {
                this.style.transform = 'scale(1.05) rotate(5deg)';
            });
            
            card.addEventListener('mouseleave', function() {
                this.style.transform = 'scale(1) rotate(0deg)';
            });
        });
    </script>
</body>
</html>


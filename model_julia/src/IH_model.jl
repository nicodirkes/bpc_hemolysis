import DifferentialEquations as DE
using QuadGK
using HypergeometricFunctions


function IH_powerLaw_stressBased(t_exp, sigma_exp, A, alpha, beta)
    """
        Stress-based power law based on doi.org/10.1016/j.cma.2024.116979
        Sensible limits for the parameters:
        0 <= A <= 20 (in the paper it is C with range 1e-5 to 1e-3)
        0.5 <= alpha <= 2.5 (in the paper it is beta with range 1.2 to 2.5)
        0.01 <= beta <= 1 (in the paper it is alpha with the range 0.1 to 1)
    """
    # Compute IH%
    return exp(-A) * (sigma_exp^alpha) * (t_exp^beta) * 100  # convert to percentage
end

function IH_powerLaw_strainBased_ivp(t_exp, sigma_exp, A, alpha, beta)
    """
    Strain-based power law model for IH.
    """
    # Parametersk
    f1 = 5.0

    function integrand(u, p, t)
        sigma_exp, f1, alpha, beta = p
        (sigma_exp * (1.0 - exp(-f1 * t)))^(alpha / beta)
    end

    try
        # Compute G_int
        u0 = 0.0
        tspan = (0.0, t_exp)
        p = [sigma_exp, f1, alpha, beta]
        prob = DE.ODEProblem(integrand, u0, tspan, p)
        sol = DE.solve(prob)
        G_int = sol[end]

        # Compute IH%
        return exp(-A) * G_int^beta * 100 # convert to percentage
    catch e
        return NaN
    end

end

function IH_powerLaw_strainBased_ivp_regularized(t_exp, sigma_exp, A, alpha, beta; regularizer=0.01)
    """
    Strain-based power law model for IH.
    """
    # Parameters
    f1 = 5.0

    function integrand(u, p, t)
        sigma_exp, f1, alpha, beta = p
        (regularizer * sigma_exp * (1.0 - exp(-f1 * t)))^(alpha / beta)
    end

    try
        # Compute G_int
        u0 = 0.0
        tspan = (0.0, t_exp)
        p = [sigma_exp, f1, alpha, beta]
        prob = DE.ODEProblem(integrand, u0, tspan, p)
        sol = DE.solve(prob)
        G_int = sol[end]

        # Compute IH%
        return (1.0/regularizer)^alpha * exp(-A) * G_int^beta * 100 # convert to percentage
    catch e
        return NaN
    end

end

function IH_powerLaw_strainBased_ivp_reformulated(t_exp, sigma_exp, A, alpha, beta)
    """
    Strain-based power law model for IH.
    """
    # Parameters
    f1 = 5.0

    function integrand(u, p, t)
        f1, alpha, beta = p
        (1.0 - exp(-f1 * t))^(alpha / beta)
    end

    try
        # Compute G_int
        u0 = 0.0
        tspan = (0.0, t_exp)
        p = [f1, alpha, beta]
        prob = DE.ODEProblem(integrand, u0, tspan, p)
        sol = DE.solve(prob)
        G_int = sol[end]

        # Compute IH%
        return exp(-A) * sigma_exp^alpha * G_int^beta * 100 # convert to percentage
    catch e
        return NaN
    end

end

function IH_powerLaw_strainBased_quad(t_exp, sigma_exp, A, alpha, beta)
    """
    Strain-based power law model for IH.
    """
    # Parameters
    f1 = 5.0

    try
        # Compute G_int
        G_int, _ = quadgk(t -> (sigma_exp * (1.0 - exp(-f1 * t)))^(alpha / beta), 0, t_exp)
        # Compute IH%
        return exp(-A) * G_int^beta * 100 # convert to percentage
    catch e
        return NaN
    end

end

function IH_powerLaw_strainBased_quad_regularized(t_exp, sigma_exp, A, alpha, beta; regularizer=0.01)
    """
    Strain-based power law model for IH.
    """
    # Parameters
    f1 = 5.0

    try
        # Compute G_int
        G_int, _ = quadgk(t -> (regularizer * sigma_exp * (1.0 - exp(-f1 * t)))^(alpha / beta), 0, t_exp)
        # Compute IH%
        return (1.0/regularizer)^alpha * exp(-A) * G_int^beta * 100 # convert to percentage
    catch e
        return NaN
    end

end

function IH_powerLaw_strainBased_quad_reformulated(t_exp, sigma_exp, A, alpha, beta)
    """
    Strain-based power law model for IH.
    """
    # Parameters
    f1 = 5.0

    try
        # Compute G_int
        G_int, _ = quadgk(t -> (1.0 - exp(-f1 * t))^(alpha / beta), 0, t_exp)
        # Compute IH%
        return exp(-A) * sigma_exp^alpha * G_int^beta * 100 # convert to percentage
    catch e
        return NaN
    end

end

function IH_powerLaw_strainBased_analytical(t_exp, sigma_exp, A, alpha, beta)
    """
    Strain-based power law model for IH.
    """
    # Parameters
    f1 = 5.0

    # Constants
    m = alpha/beta
    AA = 1.0 - exp(-f1*t_exp)

    try
        # Compute G_int
        G_int = (sigma_exp^m/f1) * (AA^(m+1.0)) / (m+1.0) * HypergeometricFunctions._₂F₁(1.0, m+1.0, m+2.0, AA)
        # Compute IH%
        return exp(-A) * G_int^beta * 100 # convert to percentage
    catch e
        return NaN
    end

end

function IH_powerLaw_strainBased_analytical_reformulated(t_exp, sigma_exp, A, alpha, beta)
    """
    Strain-based power law model for IH.
    """
    # Parameters
    f1 = 5.0

    # Constants
    m = alpha/beta
    AA = 1.0 - exp(-f1*t_exp)

    try
        # Compute G_int
        G_int = 1.0/f1 * (AA^(m+1.0)) / (m+1.0) * HypergeometricFunctions._₂F₁(1.0, m+1.0, m+2.0, AA)
        # Compute IH%
        return exp(-A) * sigma_exp^alpha * G_int^beta * 100 # convert to percentage
    catch e
        return NaN
    end

end



function IH_poreFormation_stressBased(t_exp, sigma_exp, h, k)
    """
    Compute IH% with pore formation model based on stress-based morphology.
    Sensible limits:
    0 <= h <= 20
    0 <= k <= 2
    """
    # Parameters
    mu=0.0035

    function computePoreAreaInterpolated(G)
        # Polynomial coefficients for the area strain to pore area conversion (fifth order polynomial fit)
        p = [-0.1593, 0.6332, 32.3921, -48.9149, 37.3125, -13.4134]
        G1 = 3750
        G2 = 42000

        if G < G1
            return 0.0
        elseif G > G2
            return sum(p)
        else
            G_norm = G / G2
            return p[6]*G_norm^5 + p[5]*G_norm^4 + p[4]*G_norm^3 + p[3]*G_norm^2 + p[2]*G_norm + p[1]
        end
    end

    G_exp = sigma_exp / mu # shear rate

    Apt = computePoreAreaInterpolated(G_exp) * t_exp

    # Compute IH%
    return exp(-h) * (sigma_exp^k) * Apt * 100 # convert to percentage


end

function IH_poreFormation_strainBased_ivp(t_exp, sigma_exp, h, k)
    """
    Compute IH% with pore formation model based on strain-based morphology.
    Sensible limits:
    0 <= h <= 20
    0 <= k <= 2
    """
    # Parameters
    f1=5.0
    mu=0.0035

    function computePoreAreaInterpolated(G)
        # Polynomial coefficients for the area strain to pore area conversion (fifth order polynomial fit)
        p = [-0.1593, 0.6332, 32.3921, -48.9149, 37.3125, -13.4134]
        G1 = 3750
        G2 = 42000

        if G < G1
            return 0.0
        elseif G > G2
            return sum(p)
        else
            G_norm = G / G2
            return p[6]*G_norm^5 + p[5]*G_norm^4 + p[4]*G_norm^3 + p[3]*G_norm^2 + p[2]*G_norm + p[1]
        end
    end

    function integrand(u, p, t)
        G_exp, f1 = p
        computePoreAreaInterpolated(G_exp * (1.0 - exp(-f1 * t)))
    end

    try
        G_exp = sigma_exp / mu # shear rate

        # Compute Apt
        u0 = 0.0
        tspan = (0.0, t_exp)
        p = [G_exp, f1]
        prob = DE.ODEProblem(integrand, u0, tspan, p)
        sol = DE.solve(prob)
        Apt = sol[end]

        # Compute IH%
        return exp(-h) * (sigma_exp^k) * Apt * 100 # convert to percentage
    catch e
        return NaN
    end

 


end

function IH_poreFormation_strainBased_ivp_regularized(t_exp, sigma_exp, h, k; regularizer=0.01)
    """
    Compute IH% with pore formation model based on strain-based morphology.
    Sensible limits:
    0 <= h <= 20
    0 <= k <= 2
    """
    # Parameters
    f1=5.0
    mu=0.0035

    function computePoreAreaInterpolated(G)
        # Polynomial coefficients for the area strain to pore area conversion (fifth order polynomial fit)
        p = [-0.1593, 0.6332, 32.3921, -48.9149, 37.3125, -13.4134]
        G1 = 3750
        G2 = 42000

        if G < G1
            return 0.0
        elseif G > G2
            return sum(p)
        else
            G_norm = G / G2
            return p[6]*G_norm^5 + p[5]*G_norm^4 + p[4]*G_norm^3 + p[3]*G_norm^2 + p[2]*G_norm + p[1]
        end
    end

    function integrand(u, p, t)
        G_exp, f1 = p
        regularizer * computePoreAreaInterpolated(G_exp * (1.0 - exp(-f1 * t)))
    end

    try
        G_exp = sigma_exp / mu # shear rate

        # Compute Apt
        u0 = 0.0
        tspan = (0.0, t_exp)
        p = [G_exp, f1]
        prob = DE.ODEProblem(integrand, u0, tspan, p)
        sol = DE.solve(prob)
        Apt = sol[end]

        # Compute IH%
        return (1.0 / regularizer) * exp(-h) * (sigma_exp^k) * Apt * 100 # convert to percentage
    catch e
        return NaN
    end

 


end

function IH_poreFormation_strainBased_quad(t_exp, sigma_exp, h, k)
    """
    Compute IH% with pore formation model based on strain-based morphology.
    Sensible limits:
    0 <= h <= 20
    0 <= k <= 2
    """
    # Parameters
    f1=5.0
    mu=0.0035

    function computePoreAreaInterpolated(G)
        # Polynomial coefficients for the area strain to pore area conversion (fifth order polynomial fit)
        p = [-0.1593, 0.6332, 32.3921, -48.9149, 37.3125, -13.4134]
        G1 = 3750
        G2 = 42000

        if G < G1
            return 0.0
        elseif G > G2
            return sum(p)
        else
            G_norm = G / G2
            return p[6]*G_norm^5 + p[5]*G_norm^4 + p[4]*G_norm^3 + p[3]*G_norm^2 + p[2]*G_norm + p[1]
        end
    end

    try
        G_exp = sigma_exp / mu # shear rate
        # Compute Apt
        Apt, _ = quadgk(t -> computePoreAreaInterpolated(G_exp * (1.0 - exp(-f1 * t))), 0, t_exp)
        # Compute IH%
        return exp(-h) * (sigma_exp^k) * Apt * 100 # convert to percentage
    catch e
        return NaN
    end

 


end

function IH_poreFormation_strainBased_quad_regularized(t_exp, sigma_exp, h, k; regularizer=0.01)
    """
    Compute IH% with pore formation model based on strain-based morphology.
    Sensible limits:
    0 <= h <= 20
    0 <= k <= 2
    """
    # Parameters
    f1=5.0
    mu=0.0035

    function computePoreAreaInterpolated(G)
        # Polynomial coefficients for the area strain to pore area conversion (fifth order polynomial fit)
        p = [-0.1593, 0.6332, 32.3921, -48.9149, 37.3125, -13.4134]
        G1 = 3750
        G2 = 42000

        if G < G1
            return 0.0
        elseif G > G2
            return sum(p)
        else
            G_norm = G / G2
            return p[6]*G_norm^5 + p[5]*G_norm^4 + p[4]*G_norm^3 + p[3]*G_norm^2 + p[2]*G_norm + p[1]
        end
    end

    try
        G_exp = sigma_exp / mu # shear rate
        # Compute Apt
        Apt, _ = quadgk(t -> regularizer * computePoreAreaInterpolated(G_exp * (1.0 - exp(-f1 * t))), 0, t_exp)
        # Compute IH%
        return (1.0 / regularizer) * exp(-h) * (sigma_exp^k) * Apt * 100 # convert to percentage
    catch e
        return NaN
    end

 


end



function IH_poreFormation_strainBased_analytical_binomial(t_exp, sigma_exp, h, k)


    f1=5.0
    mu=0.0035

    G_exp = sigma_exp / mu  # shear rate


    function integrate_normalized_Geff(f, i, t0, t1)
        """
        Helper function to integrate (1 - exp(-f*t))^i from t0 to t1.
        """
        # if i is an integer, we can use the binomial expansion
        integral = 0.0
        if isa(i, Integer) && i >= 1
            for k in 1:i
                binom = binomial(i, k)
                integral += binom * (-1)^(k+1) / k * (exp(-k*f*t1) - exp(-k*f*t0))
            end
        end
        integral = integral / f + (t1 - t0)
        return integral
    end 


    function integral_poreFormation_analytical(t_exp, G, f)
        """
        Model #3: Compute IH with pore formation model based on strain-based morphology.
        Use analytical integration formula.
        """


        # Polynomial coefficients for the area strain to pore area conversion (fifth order polynomial fit)
        p = [-0.1593, 0.6332, 32.3921, -48.9149, 37.3125, -13.4134]
        G1 = 3750.0
        G2 = 42000.0


        # Analytical integral of pore area formation
        # First: find transition time points where G_eff crosses interpolation limits
        t1 = (G > G1) ? (-log(1.0 - G1 / G) / f) : t_exp
        t1 = min(t1, t_exp)
        t2 = (G > G2) ? (-log(1.0 - G2 / G) / f) : t_exp
        t2 = min(t2, t_exp)

        # Integrate in three parts
        # Part 1: from 0 to t1
        integral = 0.0  # pore area is zero in this range
        # Part 2: from t1 to t2 (if applicable)
        if t2 > t1
            for i in 0:5  # iterate over polynomial terms
                integral += p[i+1] * (G/G2)^i * integrate_normalized_Geff(f, i, t1, t2)
            end
        end

        # Part 3: from t2 to t_exp (if applicable)
        if t_exp > t2
            integral += sum(p) * (t_exp - t2)
        end
        return integral
    end


    # Compute integral of pore area formation
    Apt = integral_poreFormation_analytical(t_exp, G_exp, f1)

    return exp(-h) * (sigma_exp^k) * Apt * 100 # convert to percentage
end


function IH_poreFormation_strainBased_analytical_hypergeometric(t_exp, sigma_exp, h, k)


    f1=5.0
    mu=0.0035

    G_exp = sigma_exp / mu  # shear rate


    function integrate_normalized_Geff(f, i, t0, t1)
        """
        Helper function to integrate (1 - exp(-f*t))^i from t0 to t1.
        """
        integral = (1 - exp(-f*t1))^(i+1) * HypergeometricFunctions._₂F₁(1, i+1, i+2, 1 - exp(-f*t1)) / (f * (i+1)) - (1 - exp(-f*t0))^(i+1) * HypergeometricFunctions._₂F₁(1, i+1, i+2, 1 - exp(-f*t0)) / (f * (i+1))
        return integral
    end 


    function integral_poreFormation_analytical(t_exp, G, f)
        """
        Model #3: Compute IH with pore formation model based on strain-based morphology.
        Use analytical integration formula.
        """


        # Polynomial coefficients for the area strain to pore area conversion (fifth order polynomial fit)
        p = [-0.1593, 0.6332, 32.3921, -48.9149, 37.3125, -13.4134]
        G1 = 3750.0
        G2 = 42000.0


        # Analytical integral of pore area formation
        # First: find transition time points where G_eff crosses interpolation limits
        t1 = (G > G1) ? (-log(1.0 - G1 / G) / f) : t_exp
        t1 = min(t1, t_exp)
        t2 = (G > G2) ? (-log(1.0 - G2 / G) / f) : t_exp
        t2 = min(t2, t_exp)

        # Integrate in three parts
        # Part 1: from 0 to t1
        integral = 0.0  # pore area is zero in this range
        # Part 2: from t1 to t2 (if applicable)
        if t2 > t1
            for i in 0:5  # iterate over polynomial terms
                integral += p[i+1] * (G/G2)^i * integrate_normalized_Geff(f, i, t1, t2)
            end
        end

        # Part 3: from t2 to t_exp (if applicable)
        if t_exp > t2
            integral += sum(p) * (t_exp - t2)
        end
        return integral
    end


    # Compute integral of pore area formation
    Apt = integral_poreFormation_analytical(t_exp, G_exp, f1)

    return exp(-h) * (sigma_exp^k) * Apt * 100 # convert to percentage
end

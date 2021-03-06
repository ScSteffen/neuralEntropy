using LinearAlgebra
using KitBase, KitBase.FastGaussQuadrature, KitBase.ProgressMeter, KitBase.JLD2, KitBase.Plots
using KitML, KitML.Flux, KitML.DiffEqFlux, KitML.Optim

fnn = FastChain(FastDense(3, 15, tanh), FastDense(15, 30, tanh), FastDense(30, 30, tanh), FastDense(30, 15, tanh), FastDense(15, 3))

function flux_wall!(
    ff::T1,
    f::T2,
    u::T3,
    dt,
    rot = 1,
) where {
    T1<:AbstractVector{<:AbstractFloat},
    T2<:AbstractVector{<:AbstractFloat},
    T3<:AbstractVector{<:AbstractFloat},
}
    δ = heaviside.(u .* rot)
    fWall = 0.5 .* δ .+ f .* (1.0 .- δ)
    @. ff = u * fWall * dt

    return nothing
end

begin
    # setup
    set = Setup("radiation", "linesource", "1d1f1v", "kfvs", "bgk", 1, 2, "vanleer", "extra", 0.5, 0.5)

    # physical space
    x0 = 0
    x1 = 1
    nx = 100
    nxg = 0
    ps = PSpace1D(x0, x1, nx, nxg)

    # velocity space
    nu = 28
    points, weights = gausslegendre(nu)
    vs = VSpace1D(points[1], points[end], nu, points, ones(nu) .* (points[end] - points[1]) / (nu - 1), weights)

    # material
    σs = ones(Float32, nx)
    σa = zeros(Float32, nx)
    σt = σs + σa
    σq = zeros(Float32, nx)

    # moments
    L = 2
    ne = 3
    m = eval_sphermonomial(points, L)

    # time
    dt = set.cfl * ps.dx[1]
    nt = set.maxTime / dt |> floor |> Int
    global t = 0.0

    # solution
    f0 = 0.0001 * ones(nu)
    phi = zeros(ne, nx)
    for i = 1:nx
        phi[:, i] .= m * f0
    end
    α = zeros(Float32, ne, nx)

    # NN
    αT = zeros(Float32, nx, ne)
    phiT = zeros(Float32, nx, ne)
    phi_old = zeros(Float32, ne, nx)
    phi_temp = deepcopy(phi_old)
    
    opt = optimize_closure(zeros(Float32, ne), m, weights, phi[:, 1], KitBase.maxwell_boltzmann_dual)
    
    global X = zeros(Float32, ne, 1)
    X[:, 1] .= phi[:, 1]
    global Y = zeros(Float32, ne, 1) # α
    Y[:, 1] = opt.minimizer

    cd(@__DIR__)
end

begin
    # initial condition
    f0 = 0.0001 * ones(nu)
    phi = zeros(ne, nx)
    for i = 1:nx
        phi[:, i] .= m * f0
    end
    α = zeros(Float32, ne, nx)
    flux = zeros(Float32, ne, nx + 1)
    fη = zeros(nu)
end

for iter = 1:nt
    println("iteration $iter of $nt")

    # mathematical optimizer
    @inbounds for i = 1:nx
        opt = KitBase.optimize_closure(α[:, i], m, weights, phi[:, i], KitBase.maxwell_boltzmann_dual)
        α[:, i] .= opt.minimizer
        phi[:, i] .= KitBase.realizable_reconstruct(opt.minimizer, m, weights, KitBase.maxwell_boltzmann_dual_prime)
    
        #X = hcat(X, phi[:, i])
        #Y = hcat(Y, kinetic_entropy(α[:, i], m, weights))
    end

    flux_wall!(fη, maxwell_boltzmann_dual.(α[:, 1]' * m)[:], points, dt, 1.0)
    for k in axes(flux, 1)
        flux[k, 1] = sum(m[k, :] .* weights .* fη)
    end

    @inbounds for i = 2:nx
        KitBase.flux_kfvs!(fη, KitBase.maxwell_boltzmann_dual.(α[:, i-1]' * m)[:], KitBase.maxwell_boltzmann_dual.(α[:, i]' * m)[:], points, dt)
        
        for k in axes(flux, 1)
            flux[k, i] = sum(m[k, :] .* weights .* fη)
        end
    end

    @inbounds for i = 1:nx-1
        for q = 1:1
            phi[q, i] =
                phi[q, i] +
                (flux[q, i] - flux[q, i+1]) / ps.dx[i] +
                (σs[i] * phi[q, i] - σt[i] * phi[q, i]) * dt +
                σq[i] * dt
        end

        for q = 2:ne
            phi[q, i] =
                phi[q, i] +
                (flux[q, i] - flux[q, i+1]) / ps.dx[i] +
                (-σt[i] * phi[q, i]) * dt
        end
    end
    phi[:, nx] .=  phi[:, nx-1]

    global t += dt
end

phi_ref = deepcopy(phi)
for i = 1:nx
    global X = hcat(X, phi[:, i])
    #Y = hcat(Y, kinetic_entropy(α[:, i], m, weights))
    global Y = hcat(Y, α[:, i])
end

res = sci_train(fnn, (X, Y))
res = sci_train(fnn, (X, Y), res.u; maxiters=50000, device=gpu)
res = sci_train(fnn, (X, Y), res.u, LBFGS(); maxiters=5000, device=cpu)

X_old = deepcopy(X)
Y_old = deepcopy(Y)

begin
    # initial condition
    f0 = 0.0001 * ones(nu)
    phi = zeros(ne, nx)
    for i = 1:nx
        phi[:, i] .= m * f0
    end
    α = zeros(Float32, ne, nx)
    flux = zeros(Float32, ne, nx + 1)
    fη = zeros(nu)
end


#anim = @animate for iter = 1:nt
for iter = 1:nt
    println("iteration $iter of $nt")
    phi_old .= phi

    # regularization
    α .= fnn(phi_old, res.u)
    @inbounds Threads.@threads for i = 1:nx
        phi_temp[:, i] .= KitBase.realizable_reconstruct(α[:, i], m, weights, KitBase.maxwell_boltzmann_dual_prime)
    end

    counter = 0
    @inbounds for i = 1:nx
        if norm(phi_temp[:, i] .- phi_old[:, i], 1) > 1e-3
            counter +=1

            opt = KitBase.optimize_closure(α[:, i], m, weights, phi[:, i], KitBase.maxwell_boltzmann_dual)
            α[:, i] .= opt.minimizer
            phi[:, i] .= KitBase.realizable_reconstruct(opt.minimizer, m, weights, KitBase.maxwell_boltzmann_dual_prime)

            #X = hcat(X, phi[:, i])
            #Y = hcat(Y, kinetic_entropy(α[:, i], m, weights))
            #Y = hcat(Y, α[:, i])
        else
            phi[:, i] .= phi_temp[:, i]
        end
    end
    println("newton: $counter of $nx")

    flux_wall!(fη, maxwell_boltzmann_dual.(α[:, 1]' * m)[:], points, dt, 1.0)
    for k in axes(flux, 1)
        flux[k, 1] = sum(m[k, :] .* weights .* fη)
    end

    @inbounds for i = 2:nx
        KitBase.flux_kfvs!(fη, KitBase.maxwell_boltzmann_dual.(α[:, i-1]' * m)[:], KitBase.maxwell_boltzmann_dual.(α[:, i]' * m)[:], points, dt)
        
        for k in axes(flux, 1)
            flux[k, i] = sum(m[k, :] .* weights .* fη)
        end
    end

    @inbounds for i = 1:nx-1
        for q = 1:1
            phi[q, i] =
                phi[q, i] +
                (flux[q, i] - flux[q, i+1]) / ps.dx[i] +
                (σs[i] * phi[q, i] - σt[i] * phi[q, i]) * dt +
                σq[i] * dt
        end

        for q = 2:ne
            phi[q, i] =
                phi[q, i] +
                (flux[q, i] - flux[q, i+1]) / ps.dx[i] +
                (-σt[i] * phi[q, i]) * dt
        end
    end
    phi[:, nx] .=  phi[:, nx-1]

    global t += dt

    if iter%19 == 0 && counter > nx÷2
        global res = KitML.sci_train(fnn, (X, Y), res.u, LBFGS(); maxiters=2000)
    end

    #plot(ps.x[1:nx], phi[1, :])
end

#gif(anim, "alpha_1d.gif")

plot(ps.x[1:nx], phi_ref[1, :], xlabel="x", ylabel="u₀", label="ref", color=:gray32, lw=2)
scatter!(ps.x[1:nx], phi[1, :], label="unified")
#savefig("1du0_t0.3.pdf")

#=
using BenchmarkTools
@benchmark fnn(phi_old, p_best)

@benchmark for i = 1:nx
    KitBase.optimize_closure(α[:, i], m, weights, phi[:, i], KitBase.maxwell_boltzmann_dual)
end
=#
begin
    _α0 = zeros(Float32, ne, nx)
    _α1 = zero(_α0)
    for i = 1:nx
        _α1[:, i] .= fnn(phi[:, i], res.u)

        opt = KitBase.optimize_closure(_α0[:, i], m, weights, phi[:, i], KitBase.maxwell_boltzmann_dual)
        _α0[:, i] .= opt.minimizer
    end
end

plot(ps.x[1:nx], _α0')
plot!(ps.x[1:nx], _α1', line=:dash)
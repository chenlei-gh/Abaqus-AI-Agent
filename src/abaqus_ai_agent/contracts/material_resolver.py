"""MaterialResolver engine for mapping physical MaterialRecord to canonical Abaqus MaterialDefinition.

Enforces constitutive sanity, anti-hallucination gates, environmental condition matching,
and unit system conversions.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .material import ElasticProperties, MaterialDefinition, PlasticProperties, ThermalProperties
from .material_record import MaterialCondition, MaterialProperty, MaterialRecord
from .units import UnitSystem


@dataclass(frozen=True)
class MaterialResolutionResult:
    """Outcome of resolving a real-world MaterialRecord into an Abaqus MaterialDefinition."""
    status: str                              # "RESOLVED", "ASSISTED", "BLOCKED", "UNSUPPORTED"
    material_definition: Optional[MaterialDefinition]
    diagnostics: Tuple[str, ...] = ()
    assumptions: Tuple[str, ...] = ()
    evidence_source: str = ""

    @property
    def is_executable(self) -> bool:
        return self.status in ("RESOLVED", "ASSISTED") and self.material_definition is not None


class MaterialResolver:
    """Constitutive mapper and gatekeeper between external material data and solver models."""

    @staticmethod
    def _convert_stress(val: float, from_unit: str, target_system: UnitSystem) -> float:
        """Convert stress/modulus quantity to target unit system."""
        # Standardize from_unit
        u = from_unit.strip().lower()
        # Convert to Pa first
        if u in ("mpa", "n/mm2", "n/mm^2"):
            pa_val = val * 1e6
        elif u in ("gpa", "kn/mm2"):
            pa_val = val * 1e9
        elif u in ("kpa",):
            pa_val = val * 1e3
        elif u in ("pa", "n/m2", "n/m^2"):
            pa_val = val
        elif u in ("psi",):
            pa_val = val * 6894.757
        elif u in ("bar",):
            pa_val = val * 1e5
        elif u in ("mbar",):
            pa_val = val * 100.0
        else:
            raise ValueError(
                f"Unrecognized or unsupported stress unit '{from_unit}'; unknown unit fallback is strictly rejected."
            )

        # Convert Pa to target system stress
        if target_system.name in ("MM_N_MPA", "SI_MM"):
            return pa_val / 1e6  # to MPa
        return pa_val  # to Pa for SI / M_N_PA

    @staticmethod
    def _convert_density(val: float, from_unit: str, target_system: UnitSystem) -> float:
        """Convert density quantity to target unit system."""
        u = from_unit.strip().lower()
        # Convert to kg/m3 first
        if u in ("g/cm3", "g/cm^3", "g/ml", "kg/l"):
            kg_m3 = val * 1000.0
        elif u in ("kg/m3", "kg/m^3"):
            kg_m3 = val
        elif u in ("tonne/mm3", "tonne/mm^3", "t/mm3"):
            kg_m3 = val * 1e12
        elif u in ("mg/mm3", "mg/mm^3"):
            kg_m3 = val * 1000.0
        else:
            raise ValueError(
                f"Unrecognized or unsupported density unit '{from_unit}'; unknown unit fallback is strictly rejected."
            )

        # Convert kg/m3 to target system density
        if target_system.name in ("MM_N_MPA", "SI_MM"):
            return kg_m3 * 1e-12  # tonne/mm3
        return kg_m3  # kg/m3 for SI

    @staticmethod
    def _convert_thermal_conductivity(val: float, from_unit: str, target_system: UnitSystem) -> float:
        """Convert thermal conductivity to target unit system."""
        if not math.isfinite(val) or val <= 0.0:
            raise ValueError(f"Thermal conductivity must be a positive finite number, got {val}.")
        u = from_unit.strip().lower().replace("·", "*").replace("-", "*").replace(" ", "")
        if u in ("w/(m*k)", "w/(m*c)", "w/m*k", "w/m*c", "w/m/k", "w/m/c", "w/(m.k)"):
            w_mk = val
        elif u in ("mw/(mm*k)", "mw/(mm*c)", "mw/mm*k", "mw/mm*c"):
            w_mk = val  # 1 mW/(mm*K) = 1 W/(m*K)
        elif u in ("w/(mm*k)", "w/(mm*c)", "w/mm*k", "w/mm*c"):
            w_mk = val * 1000.0
        elif u in ("cal/(cm*s*c)", "cal/(cm*s*k)", "cal/cm*s*c", "cal/cm*s*k"):
            w_mk = val * 418.68
        elif u in ("btu/(hr*ft*f)", "btu/(hr*ft*r)", "btu/hr*ft*f"):
            w_mk = val * 1.730735
        else:
            raise ValueError(
                f"Unrecognized or unsupported thermal conductivity unit '{from_unit}'; unknown unit fallback is strictly rejected."
            )
        # In MM_N_MPA (mW/(mm*K)), the numerical value is identical to W/(m*K)
        return w_mk

    @staticmethod
    def _convert_expansion_coefficient(val: float, from_unit: str) -> float:
        """Convert thermal expansion coefficient to 1/K."""
        if not math.isfinite(val):
            raise ValueError(f"Thermal expansion coefficient must be a finite number, got {val}.")
        u = from_unit.strip().lower().replace("·", "*").replace("-", "*").replace(" ", "")
        if u in ("1/k", "1/c", "1/degc", "1/degk", "k^-1", "c^-1", "k^(-1)", "c^(-1)"):
            c_val = val
        elif u in ("ppm/k", "ppm/c", "ppm/degc", "ppm/degk", "um/(m*k)", "um/(m*c)", "um/m*k", "um/m*c", "1e-6/k", "1e-6/c", "10^-6/k", "10^-6/c"):
            c_val = val * 1e-6
        elif u in ("1/f", "1/degf", "f^-1", "f^(-1)"):
            c_val = val * 1.8
        elif u in ("ppm/f", "ppm/degf", "1e-6/f"):
            c_val = val * 1.8 * 1e-6
        else:
            raise ValueError(
                f"Unrecognized or unsupported thermal expansion unit '{from_unit}'; unknown unit fallback is strictly rejected."
            )
        if abs(c_val) > 0.05:
            raise ValueError(
                f"Unphysical thermal expansion coefficient magnitude {c_val} (1/K); must be <= 0.05."
            )
        return c_val

    @classmethod
    def resolve(
        cls,
        record: MaterialRecord,
        target_temperature: Optional[float] = None,
        target_temperature_unit: str = "C",
        target_humidity: str = "dry",
        constitutive_intent: str = "linear_elastic",
        target_unit_system: str = "MM_N_MPA",
        allow_assisted_assumptions: bool = True,
        operating_strain_rate: Optional[float] = None,
        operating_duration: Optional[float] = None,
        test_standard: Optional[str] = None,
    ) -> MaterialResolutionResult:
        """Resolve a MaterialRecord into an executable Abaqus MaterialDefinition.

        Args:
            record: Canonical MaterialRecord with experimental properties/curves.
            target_temperature: Operating temperature (in deg C). Defaults to record default.
            target_humidity: Environmental humidity condition ("dry", "conditioned").
            constitutive_intent: "linear_elastic", "elastoplastic", "viscoelastic", "creep".
            target_unit_system: Desired solver unit system ("MM_N_MPA", "SI").
            allow_assisted_assumptions: Whether engineering approximations are permitted.
            operating_strain_rate: Specific operating strain rate (1/s).
            operating_duration: Sustained loading duration for creep/viscoelasticity (s).
            test_standard: Preferred testing standard (e.g. "ISO 527-1/-2").
        """
        diagnostics: List[str] = []
        assumptions: List[str] = []
        unit_sys = UnitSystem.named(target_unit_system)

        # 1. Environmental Condition Preflight with full temperature normalization
        if target_temperature is not None:
            try:
                temp_cond = MaterialCondition(
                    temperature=target_temperature,
                    temperature_unit=target_temperature_unit,
                )
                req_temp = temp_cond.temperature_in_c
            except ValueError as ve:
                return MaterialResolutionResult(
                    status="BLOCKED",
                    material_definition=None,
                    diagnostics=(f"Invalid target temperature: {ve}",),
                    evidence_source=record.source.locator,
                )
        else:
            try:
                req_temp = record.default_condition.temperature_in_c
            except ValueError as ve:
                return MaterialResolutionResult(
                    status="BLOCKED",
                    material_definition=None,
                    diagnostics=(f"Invalid default condition temperature: {ve}",),
                    evidence_source=record.source.locator,
                )

        try:
            available_temps = {
                p.condition.temperature_in_c for p in record.properties if p.condition is not None
            }
            available_temps.add(record.default_condition.temperature_in_c)
            for c in record.curves:
                available_temps.add(c.condition.temperature_in_c)
        except ValueError as ve:
            return MaterialResolutionResult(
                status="BLOCKED",
                material_definition=None,
                diagnostics=(f"Unrecognized temperature unit in material condition: {ve}",),
                evidence_source=record.source.locator,
            )

        temp_diff = min(abs(req_temp - t) for t in available_temps)
        # Strict anti-extrapolation: even under assisted mode, refuse extreme thermal shift (> 50C)
        if temp_diff > 50.0 or (temp_diff > 25.0 and not allow_assisted_assumptions):
            return MaterialResolutionResult(
                status="BLOCKED",
                material_definition=None,
                diagnostics=(
                    f"Operating temperature {req_temp} C has no close experimental data "
                    f"(closest available: {min(available_temps, key=lambda t: abs(req_temp - t))} C, diff={temp_diff:.1f} C). "
                    "Fail-closed on uncharacterized thermal degradation/glass transition.",
                ),
                evidence_source=record.source.locator,
            )
        if temp_diff > 25.0:
            assumptions.append(
                f"Operating temperature {req_temp} C extrapolated from test data at "
                f"{min(available_temps, key=lambda t: abs(req_temp - t))} C (thermal shift uncalibrated)."
            )

        # 2. Extract Young's Modulus & Poisson's ratio
        cond_query = MaterialCondition(
            temperature=req_temp,
            temperature_unit="C",
            humidity_state=target_humidity,
            strain_rate=operating_strain_rate,
            test_time=operating_duration,
            test_standard=test_standard,
        )
        prop_e = record.get_property("youngs_modulus", cond_query) or record.get_property("tensile_modulus", cond_query)
        if prop_e is None:
            # Check if property exists under unconditioned query to provide informative diagnostics
            fallback_prop = record.get_property("youngs_modulus") or record.get_property("tensile_modulus")
            diag_msg = f"Missing youngs_modulus for requested condition (T={req_temp}C, humidity={target_humidity}"
            if operating_strain_rate:
                diag_msg += f", strain_rate={operating_strain_rate}"
            if operating_duration:
                diag_msg += f", duration={operating_duration}"
            diag_msg += ")."
            if fallback_prop and fallback_prop.condition:
                diag_msg += f" Closest available test condition was T={fallback_prop.condition.temperature_in_c}C, {fallback_prop.condition.humidity_state}."
            return MaterialResolutionResult(
                status="BLOCKED",
                material_definition=None,
                diagnostics=(diag_msg,),
                evidence_source=record.source.locator,
            )

        try:
            E_val = cls._convert_stress(prop_e.value, prop_e.unit, unit_sys)
        except ValueError as ve:
            return MaterialResolutionResult(
                status="BLOCKED",
                material_definition=None,
                diagnostics=(str(ve),),
                evidence_source=record.source.locator,
            )
        if E_val <= 0 or not math.isfinite(E_val):
            return MaterialResolutionResult(
                status="BLOCKED",
                material_definition=None,
                diagnostics=(f"Invalid Young's modulus E={E_val}; must be a finite positive number.",),
                evidence_source=record.source.locator,
            )

        prop_nu = record.get_property("poissons_ratio", cond_query) or record.get_property("poisson_ratio", cond_query)
        if prop_nu is not None:
            nu_val = prop_nu.value
        else:
            # P0-7 & P1-6: Material-family-aware Poisson's ratio derivation with composite ambiguity gate
            fam = record.identity.polymer_family.upper()
            fam_tokens = set(fam.replace("-", " ").replace("_", " ").replace("/", " ").split())

            composite_keywords = ("COMPOSITE", "HYBRID", "SANDWICH", "CFRP", "GFRP", "FIBER", "FIBRE", "LAMINATE")
            is_composite = any(kw in fam for kw in composite_keywords)

            def _match_keywords(kw_list: Tuple[str, ...]) -> bool:
                for kw in kw_list:
                    k = kw.upper()
                    if len(k) <= 2:
                        if k in fam_tokens:
                            return True
                    else:
                        if k in fam:
                            return True
                return False

            if is_composite:
                return MaterialResolutionResult(
                    status="BLOCKED",
                    material_definition=None,
                    diagnostics=(
                        f"Missing Poisson's ratio for composite material family '{record.identity.polymer_family}'; "
                        "unassisted assumption is strictly prohibited as composite or anisotropic materials cannot assume isotropic default Poisson's ratio, "
                        "and strict engineering gate forbids default assumption even in assisted mode.",
                    ),
                    evidence_source=record.source.locator,
                )
            else:
                is_metal = _match_keywords(("STEEL", "FE", "IRON", "AL", "ALUMINUM", "ALUMINIUM", "TI", "TITANIUM", "COPPER", "BRASS"))
                is_polymer = _match_keywords(("PA", "POM", "PBT", "PC", "PP", "PE", "ABS", "PEEK", "PPS", "PLASTIC", "POLYMER"))

                if is_metal:
                    if _match_keywords(("STEEL", "FE", "IRON")):
                        nu_val = 0.30
                    elif _match_keywords(("AL", "ALUMINUM", "ALUMINIUM")):
                        nu_val = 0.33
                    elif _match_keywords(("TI", "TITANIUM")):
                        nu_val = 0.34
                    else:
                        nu_val = 0.34
                    assumptions.append(f"Poisson's ratio not in datasheet; assumed standard metal alloy value nu={nu_val}.")
                elif is_polymer:
                    nu_val = 0.35 if _match_keywords(("PA", "POM")) else 0.38
                    assumptions.append(f"Poisson's ratio not in datasheet; assumed standard engineering polymer value nu={nu_val}.")
                else:
                    if not allow_assisted_assumptions:
                        return MaterialResolutionResult(
                            status="BLOCKED",
                            material_definition=None,
                            diagnostics=(
                                f"Missing Poisson's ratio for unclassified material family '{record.identity.polymer_family}'; unassisted assumption is strictly prohibited.",
                            ),
                            evidence_source=record.source.locator,
                        )
                    nu_val = 0.33
                    assumptions.append(f"Poisson's ratio not in datasheet for unclassified material '{record.identity.polymer_family}'; used generic engineering assumption nu={nu_val}.")

        if not (-0.99 <= nu_val < 0.5) or not math.isfinite(nu_val):
            return MaterialResolutionResult(
                status="BLOCKED",
                material_definition=None,
                diagnostics=(f"Thermodynamically invalid Poisson's ratio nu={nu_val}; isotropic elasticity requires -1.0 < nu < 0.5.",),
                evidence_source=record.source.locator,
            )

        elastic_props = ElasticProperties(
            youngs_modulus=E_val,
            poisson_ratio=nu_val,
            temperature_dependence=(len(available_temps) > 1),
        )

        # 3. Density
        prop_rho = record.get_property("density", cond_query)
        density_val: Optional[float] = None
        if prop_rho is not None:
            try:
                density_val = cls._convert_density(prop_rho.value, prop_rho.unit, unit_sys)
            except ValueError as ve:
                return MaterialResolutionResult(
                    status="BLOCKED",
                    material_definition=None,
                    diagnostics=(str(ve),),
                    evidence_source=record.source.locator,
                )
            if density_val <= 0 or not math.isfinite(density_val):
                return MaterialResolutionResult(
                    status="BLOCKED",
                    material_definition=None,
                    diagnostics=(f"Invalid density rho={density_val}; must be a finite positive number.",),
                    evidence_source=record.source.locator,
                )

        # 4. Thermal properties (P0-2: strict thermal conversion and no unauthorized default fallback)
        prop_tc = record.get_property("thermal_conductivity", cond_query)
        prop_exp = record.get_property("expansion_coefficient", cond_query) or record.get_property("clte", cond_query)
        thermal_props: Optional[ThermalProperties] = None
        if prop_tc is not None or prop_exp is not None:
            tc_val: Optional[float] = None
            if prop_tc is not None:
                try:
                    tc_val = cls._convert_thermal_conductivity(prop_tc.value, prop_tc.unit, unit_sys)
                except ValueError as ve:
                    return MaterialResolutionResult(
                        status="BLOCKED",
                        material_definition=None,
                        diagnostics=(str(ve),),
                        evidence_source=record.source.locator,
                    )

            exp_val: Optional[float] = None
            if prop_exp is not None:
                try:
                    exp_val = cls._convert_expansion_coefficient(prop_exp.value, prop_exp.unit)
                except ValueError as ve:
                    return MaterialResolutionResult(
                        status="BLOCKED",
                        material_definition=None,
                        diagnostics=(str(ve),),
                        evidence_source=record.source.locator,
                    )

            thermal_props = ThermalProperties(
                conductivity=tc_val,
                expansion_coefficient=exp_val,
            )

        # 5. Constitutive Intent & Polymer J2 Safeguard
        plastic_props: Optional[PlasticProperties] = None
        if constitutive_intent == "elastoplastic":
            # Search for calibrated yield stress or stress-strain curve
            prop_yield = record.get_property("yield_stress", cond_query) or record.get_property("stress_at_yield", cond_query)
            curve_ss = record.get_curve("stress_strain", cond_query)

            sy_val: Optional[float] = None
            explicit_sy: Optional[float] = None
            if prop_yield is not None:
                try:
                    sy_val = cls._convert_stress(prop_yield.value, prop_yield.unit, unit_sys)
                    explicit_sy = sy_val
                except ValueError as ve:
                    return MaterialResolutionResult(
                        status="BLOCKED",
                        material_definition=None,
                        diagnostics=(str(ve),),
                        evidence_source=record.source.locator,
                    )

            hardening: List[Tuple[float, float]] = []

            if curve_ss is not None:
                # P0-6 & P0-3: Detect curve type (true vs engineering), dual-axis consistency, and strain unit validity
                x_unit_lower = (curve_ss.x_unit or "").strip().lower()
                valid_strain_units = ("%", "percent", "1", "mm/mm", "in/in", "m/m", "")
                if x_unit_lower not in valid_strain_units:
                    return MaterialResolutionResult(
                        status="BLOCKED",
                        material_definition=None,
                        diagnostics=(
                            f"Unrecognized strain unit '{curve_ss.x_unit}' in stress-strain curve; must be dimensionless or strain dimension.",
                        ),
                        evidence_source=record.source.locator,
                    )

                x_name_lower = (curve_ss.x_name or "").lower()
                y_name_lower = (curve_ss.y_name or "").lower()

                x_is_strain = any(s in x_name_lower for s in ("strain", "eps"))
                y_is_stress = any(s in y_name_lower for s in ("stress", "sig"))

                if not x_is_strain or not y_is_stress:
                    return MaterialResolutionResult(
                        status="BLOCKED",
                        material_definition=None,
                        diagnostics=(
                            f"Ambiguous stress-strain curve axis definitions: x_name='{curve_ss.x_name}' "
                            f"must express strain semantics ('strain' or 'eps'), and y_name='{curve_ss.y_name}' "
                            "must express stress semantics ('stress' or 'sig').",
                        ),
                        evidence_source=record.source.locator,
                    )

                x_has_true = "true" in x_name_lower
                y_has_true = "true" in y_name_lower
                x_has_eng = any(w in x_name_lower for w in ("eng", "nominal"))
                y_has_eng = any(w in y_name_lower for w in ("eng", "nominal"))

                if x_has_true and y_has_true:
                    if x_has_eng or y_has_eng:
                        return MaterialResolutionResult(
                            status="BLOCKED",
                            material_definition=None,
                            diagnostics=(
                                f"Conflicting stress-strain curve axis definitions: x_name='{curve_ss.x_name}' "
                                f"or y_name='{curve_ss.y_name}' contains conflicting true and engineering designations.",
                            ),
                            evidence_source=record.source.locator,
                        )
                    is_already_true = True
                elif (not x_has_true) and (not y_has_true):
                    is_already_true = False
                else:
                    return MaterialResolutionResult(
                        status="BLOCKED",
                        material_definition=None,
                        diagnostics=(
                            f"Ambiguous stress-strain curve axis definitions: x_name='{curve_ss.x_name}' "
                            f"and y_name='{curve_ss.y_name}' have mismatched true vs engineering designations.",
                        ),
                        evidence_source=record.source.locator,
                    )

                raw_pts = curve_ss.points
                if not raw_pts:
                    return MaterialResolutionResult(
                        status="BLOCKED",
                        material_definition=None,
                        diagnostics=("Empty stress-strain curve points provided.",),
                        evidence_source=record.source.locator,
                    )

                converted_pts: List[Tuple[float, float, float]] = []  # (sigma_true, eps_true, eps_p)
                last_e_raw = -math.inf

                for pt_idx, (e_nom, s_nom) in enumerate(raw_pts):
                    if not (math.isfinite(e_nom) and math.isfinite(s_nom)):
                        return MaterialResolutionResult(
                            status="BLOCKED",
                            material_definition=None,
                            diagnostics=(f"Non-finite point ({e_nom}, {s_nom}) detected in stress-strain curve.",),
                            evidence_source=record.source.locator,
                        )
                    if e_nom <= last_e_raw:
                        return MaterialResolutionResult(
                            status="BLOCKED",
                            material_definition=None,
                            diagnostics=(
                                f"Non-monotonic or duplicate strain point at index {pt_idx}: "
                                f"strain {e_nom} <= previous strain {last_e_raw}. "
                                "Raw stress-strain curve must be strictly monotonically increasing in strain.",
                            ),
                            evidence_source=record.source.locator,
                        )
                    last_e_raw = e_nom

                    e_frac = e_nom / 100.0 if x_unit_lower in ("%", "percent") else e_nom
                    if e_frac < -0.99:
                        continue
                    try:
                        s_target = cls._convert_stress(s_nom, curve_ss.y_unit, unit_sys)
                    except ValueError as ve:
                        return MaterialResolutionResult(
                            status="BLOCKED",
                            material_definition=None,
                            diagnostics=(str(ve),),
                            evidence_source=record.source.locator,
                        )

                    if is_already_true:
                        sigma_true = s_target
                        eps_true = e_frac
                    else:
                        sigma_true = s_target * (1.0 + e_frac)
                        eps_true = math.log(1.0 + e_frac) if e_frac > -0.99 else 0.0

                    eps_p = eps_true - (sigma_true / E_val)
                    converted_pts.append((sigma_true, eps_true, eps_p))

                if is_already_true:
                    assumptions.append(
                        "Experimental curve identified as true stress-true strain; avoided duplicate logarithmic/engineering conversion."
                    )

                # If yield stress was not explicitly given, deduce from offset proof stress or first plastic point
                if sy_val is None:
                    # Look for point where eps_p crosses 0.002 (0.2% offset proof stress ISO 6892 / ASTM E8)
                    for k in range(len(converted_pts)):
                        sig_t, eps_t, ep = converted_pts[k]
                        if ep >= 0.002:
                            if k > 0 and converted_pts[k - 1][2] < 0.002:
                                sig_prev, _, ep_prev = converted_pts[k - 1]
                                frac = (0.002 - ep_prev) / max(ep - ep_prev, 1e-12)
                                interp_sy = sig_prev + frac * (sig_t - sig_prev)
                                sy_val = round(interp_sy, 3)
                                assumptions.append(
                                    f"Deduced linearly interpolated 0.2% offset proof stress Rp0.2={sy_val} from experimental curve."
                                )
                            else:
                                sy_val = round(sig_t, 3)
                                assumptions.append(f"Deduced 0.2% offset yield stress {sy_val} from experimental curve.")
                            break

                    if sy_val is None and converted_pts:
                        # Fallback to point with onset of inelasticity (eps_p > 0.0005)
                        inelastic_pts = [p for p in converted_pts if p[2] > 0.0005]
                        if inelastic_pts:
                            sy_val = round(inelastic_pts[0][0], 3)
                            assumptions.append(f"Deduced initial inelastic yield stress {sy_val} from stress-strain curve.")
                elif explicit_sy is not None and converted_pts:
                    # P1-5: Check for large divergence between explicit datasheet yield and curve-derived Rp0.2
                    for k in range(len(converted_pts)):
                        sig_t, eps_t, ep = converted_pts[k]
                        if ep >= 0.002:
                            curve_rp02 = sig_t
                            rel_diff = abs(curve_rp02 - explicit_sy) / max(explicit_sy, 1e-12)
                            if rel_diff > 0.25:
                                diag_msg = (
                                    f"Explicit datasheet yield stress ({explicit_sy}) differs from curve Rp0.2 ({curve_rp02}) "
                                    f"by {rel_diff * 100.0:.1f}%, exceeding 25% threshold."
                                )
                                if not allow_assisted_assumptions:
                                    return MaterialResolutionResult(
                                        status="BLOCKED",
                                        material_definition=None,
                                        diagnostics=(diag_msg + " Unassisted mode strictly rejects yield divergence.",),
                                        evidence_source=record.source.locator,
                                    )
                                diagnostics.append(diag_msg)
                                assumptions.append(
                                    f"Yield conflict: datasheet ({explicit_sy}) vs curve ({curve_rp02}) differs by {rel_diff * 100.0:.1f}%; uncertified for final delivery."
                                )
                            break

                if sy_val is not None:
                    # First point in Abaqus hardening table must be (initial yield stress, 0.0)
                    hardening.append((round(sy_val, 3), 0.0))
                    last_ep = 0.0
                    last_sig = sy_val
                    softening_encountered = False

                    for sig_t, eps_t, ep in converted_pts:
                        if ep > 0.0001 and sig_t >= sy_val:
                            # Enforce monotonic increase in plastic strain
                            if ep > (last_ep + 0.0005):
                                if sig_t < last_sig:
                                    softening_encountered = True
                                # If stress softens without damage model, clamp to prevent solver non-convergence
                                clamped_sig = max(sig_t, last_sig)
                                hardening.append((round(clamped_sig, 3), round(ep, 5)))
                                last_ep = ep
                                last_sig = clamped_sig

                    if softening_encountered:
                        assumptions.append(
                            "Post-yield stress softening in experimental curve was clamped to prevent ill-conditioned non-convergence in standard J2 plasticity."
                        )
                    else:
                        assumptions.append("Polymer/metal tensile curve calibrated into equivalent J2 hardening curve for Abaqus solver.")

            if sy_val is not None:
                if sy_val <= 0 or not math.isfinite(sy_val):
                    return MaterialResolutionResult(
                        status="BLOCKED",
                        material_definition=None,
                        diagnostics=(f"Invalid yield stress sy={sy_val}; must be a finite positive number.",),
                        evidence_source=record.source.locator,
                    )
                if not hardening:
                    assumptions.append("Single-point yield stress used with ideal perfectly plastic assumption.")
                else:
                    # Validate hardening table integrity: first point (sy, 0.0), monotonic ep, finite values
                    if hardening[0][1] != 0.0 or hardening[0][0] <= 0:
                        return MaterialResolutionResult(
                            status="BLOCKED",
                            material_definition=None,
                            diagnostics=("Hardening table first point must have zero plastic strain and positive stress.",),
                            evidence_source=record.source.locator,
                        )
                    for k in range(len(hardening) - 1):
                        if hardening[k + 1][1] <= hardening[k][1]:
                            return MaterialResolutionResult(
                                status="BLOCKED",
                                material_definition=None,
                                diagnostics=("Hardening table plastic strain values must be strictly monotonically increasing.",),
                                evidence_source=record.source.locator,
                            )
                plastic_props = PlasticProperties(
                    yield_stress=sy_val,
                    plastic_strain=0.0,
                    hardening_table=tuple(hardening),
                )
            else:
                diagnostics.append("Constitutive intent 'elastoplastic' requested, but no yield stress or stress-strain data found.")
                if not allow_assisted_assumptions:
                    return MaterialResolutionResult(
                        status="BLOCKED",
                        material_definition=None,
                        diagnostics=tuple(diagnostics),
                        evidence_source=record.source.locator,
                    )
                # Fallback to linear elastic with warning
                assumptions.append("Degraded to linear elastic model due to absent inelastic yield data.")

        elif constitutive_intent in ("viscoelastic", "creep"):
            # Check for creep or DMA curves
            curve_creep = record.get_curve("creep_isochronous", cond_query)
            if curve_creep is None:
                return MaterialResolutionResult(
                    status="UNSUPPORTED",
                    material_definition=None,
                    diagnostics=(
                        f"Constitutive intent '{constitutive_intent}' requires experimental creep/relaxation curves, "
                        "which are not present in this MaterialRecord. Request user testing data or fall back to elastic.",
                    ),
                    evidence_source=record.source.locator,
                )
            assumptions.append(f"Time-dependent {constitutive_intent} behavior available in curves.")

        # Construct canonical MaterialDefinition
        mat_name = f"{record.identity.polymer_family}_{record.identity.manufacturer}_{record.identity.grade}".replace(" ", "_").replace("-", "_")

        provenance_str = (
            f"Provider={record.source.provider}; Locator={record.source.locator}; "
            f"Grade={record.identity.grade}; Condition={target_humidity}@{req_temp}C"
        )

        metadata_dict = {
            "identity": record.identity.to_dict(),
            "source": record.source.to_dict(),
            "resolved_condition": {"temperature": req_temp, "humidity": target_humidity},
            "constitutive_intent": constitutive_intent,
        }

        mat_def = MaterialDefinition(
            name=mat_name,
            unit_system=target_unit_system,
            elastic=elastic_props,
            density=density_val,
            plastic=plastic_props,
            thermal=thermal_props,
            provenance=provenance_str,
            assumptions=tuple(assumptions),
            metadata=metadata_dict,
        )

        status = "ASSISTED" if assumptions else "RESOLVED"
        return MaterialResolutionResult(
            status=status,
            material_definition=mat_def,
            diagnostics=tuple(diagnostics),
            assumptions=tuple(assumptions),
            evidence_source=record.source.locator,
        )
